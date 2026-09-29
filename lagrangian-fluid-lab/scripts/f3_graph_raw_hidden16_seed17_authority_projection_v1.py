#!/usr/bin/env python3
"""Bounded authority-envelope projection for the F3 seed17 runner boundary.

The seed17 runner and admission module intentionally use different layers of
the receipt contract.  Older receipts may contain the bound run identity but
not the current top-level, non-authorizing ``authority`` envelope.  This
module is the narrow adapter between those layers.

It never mints scheduler authority.  A projection is accepted only when the
caller supplies an actual external scheduler document and the existing
admission verifier authenticates its signature, nonce, namespace inode, plan,
GPU/resource snapshot, and trusted key.  Source descriptors are reread and
cross-bound locally.  The returned receipt is an in-memory projection only;
this module never rewrites a receipt or namespace state and never authorizes
Popen, a worker, a queue, formal training, or credit.

The current seed17 receipt is older than the authority-bound contract and is
missing more than the top-level envelope.  In that case the adapter emits a
precise fail-closed projection gap.  A local caller claim, a GPU probe, or a
copied JSON field cannot repair that gap.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_raw_hidden16_seed17_diagnostic_admission_v1 as admission


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.f3.graph_raw.hidden16.seed17.authority_projection.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-graph-raw-hidden16-seed17-authority-projection-v1"
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RAW-HIDDEN16-SEED17-AUTHORITY-PROJECTION-GAP-RERUN1-2026-09-29.json"
)
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")
MAX_RECEIPT_BYTES = admission.MAX_JSON_BYTES

ZERO_CREDIT: dict[str, Any] = dict(admission.ZERO_CREDIT)

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
    "receipt_sha256",
)

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
    "owner",
    "namespace_descriptor",
    "namespace",
    "nonce",
    "plan_sha256",
    "rollout_snapshot",
    "rollout_snapshot_sha256",
    "external_authority",
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

PROJECTABLE_FIELDS = ("authority",)


class ProjectionError(ValueError):
    """Malformed, unbound, or non-authorizing projection input."""


class ProjectionGap(ProjectionError):
    """The receipt needs a producer-issued reissue rather than local repair."""

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
        _fail(f"{name}.{key} must be {expected!r}")


def _absolute(path: Path | str, name: str) -> Path:
    try:
        return admission._absolute(path, name)
    except (admission.AdmissionError, TypeError, ValueError) as error:
        _fail(str(error))


def _receipt_core(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_sha256", "receipt_file"}
    }


def _receipt_digest(receipt: Mapping[str, Any], name: str = "receipt") -> str:
    digest = receipt.get("receipt_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        _fail(f"{name}.receipt_sha256 is missing or malformed")
    if digest != canonical_digest(_receipt_core(receipt)):
        _fail(f"{name}.receipt_sha256 does not bind the supplied receipt bytes")
    return digest


def _validate_identity_digest(receipt: Mapping[str, Any], name: str = "receipt") -> None:
    identity = _mapping(receipt.get("identity"), f"{name}.identity")
    digest = identity.get("identity_sha256", receipt.get("identity_sha256"))
    if not isinstance(digest, str) or len(digest) != 64:
        _fail(f"{name}.identity_sha256 is missing or malformed")
    if digest != canonical_digest(identity):
        _fail(f"{name}.identity_sha256 does not bind the immutable identity")


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
        _fail(str(error))
    if payload is None:
        _fail("source admission receipt is not a JSON object")
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
    return tuple(missing)


def describe_receipt_gap(receipt_path: Path | str) -> dict[str, Any]:
    """Describe a legacy receipt without attempting authority projection."""

    receipt, file_info = _read_receipt(receipt_path)
    missing = _missing_fields(receipt)
    projectable_missing = tuple(key for key in PROJECTABLE_FIELDS if key in missing)
    non_projectable = tuple(key for key in missing if key not in PROJECTABLE_FIELDS)
    identity = receipt.get("identity")
    identity_map = identity if isinstance(identity, Mapping) else {}
    authority_path = None
    if isinstance(identity_map.get("external_authority"), Mapping):
        authority_path = identity_map["external_authority"].get("path")
    blockers: list[str] = []
    if projectable_missing:
        blockers.append(
            "top-level authority envelope is absent; it may only be projected "
            "after external scheduler verification"
        )
    if non_projectable:
        blockers.append(
            "receipt is missing producer-bound fields that a local adapter cannot "
            f"reconstruct: {', '.join(non_projectable)}"
        )
    if authority_path is None:
        blockers.append(
            "identity.external_authority is absent; caller/local fields are not "
            "an external authority"
        )
    else:
        blockers.append(f"identity.external_authority.path={authority_path}")
    return {
        "schema": f"{SCHEMA}.gap",
        "status": "blocked_projection_gap" if (non_projectable or authority_path is None) else "projection_candidate",
        "source_receipt": file_info,
        "source_receipt_schema": receipt.get("schema"),
        "source_receipt_sha256": receipt.get("receipt_sha256"),
        "missing_fields": list(missing),
        "projectable_missing_fields": list(projectable_missing),
        "non_projectable_missing_fields": list(non_projectable),
        "external_authority_path_in_receipt": authority_path,
        "blockers": blockers,
        "historical_receipt_rewritten": False,
        "safe_local_repair": False if (non_projectable or authority_path is None) else None,
        **ZERO_CREDIT,
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
    authority = dict(_mapping(value, "authority"))
    allowed = set(AUTHORITY_FIELDS)
    unknown = sorted(set(authority) - allowed)
    if unknown:
        _fail(f"authority contains unknown fields: {unknown}")
    for key in AUTHORITY_FIELDS:
        if key not in authority:
            _fail(f"authority.{key} is missing")
    _exact(authority, "schema", admission.AUTHORITY_SCHEMA, "authority")
    for key in (
        "receipt_authorizes_popen",
        "diagnostic_execute_allowed",
        "launch_allowed",
        "formal_promotion_allowed",
        "credit_promotion_allowed",
        "formal_state_touched",
    ):
        _exact(authority, key, False, "authority")
    _exact(authority, "external_gate_required", True, "authority")
    _exact(authority, "credit", 0, "authority")


def _validate_receipt_shell(receipt: Mapping[str, Any]) -> None:
    _exact(receipt, "schema", admission.SCHEMA, "receipt")
    _exact(receipt, "status", "issued", "receipt")
    _exact(receipt, "receipt_version", 1, "receipt")
    _exact(receipt, "report_id", admission.REPORT_ID, "receipt")
    _exact(receipt, "diagnostic_execute_only", True, "receipt")
    _validate_zero_credit(receipt, "receipt")
    if "authority" in receipt:
        _validate_existing_authority(receipt["authority"])


def _validate_source_bindings(identity: Mapping[str, Any]) -> dict[str, str]:
    root = _absolute(identity["root"], "identity.root")
    manifest = dict(_mapping(identity["manifest"], "identity.manifest"))
    training = dict(_mapping(identity["training_receipt"], "identity.training_receipt"))
    checkpoint = dict(_mapping(identity["checkpoint"], "identity.checkpoint"))

    manifest_path = _absolute(manifest["path"], "identity.manifest.path")
    training_path = _absolute(training["path"], "identity.training_receipt.path")
    checkpoint_path = _absolute(checkpoint["path"], "identity.checkpoint.path")
    for path, name in (
        (manifest_path, "manifest"),
        (training_path, "training receipt"),
        (checkpoint_path, "checkpoint"),
    ):
        if not (admission._under(path, root) or admission._under(path, Path("/tmp"))):
            _fail(f"{name} escapes the bounded lab/tmp roots")

    _manifest_raw, manifest_descriptor, manifest_payload = admission._read_file(
        manifest_path,
        "current manifest",
        max_bytes=admission.MAX_JSON_BYTES,
        parse_json=True,
    )
    _training_raw, training_descriptor, training_payload = admission._read_file(
        training_path,
        "training receipt",
        max_bytes=admission.MAX_JSON_BYTES,
        parse_json=True,
    )
    checkpoint_descriptor = admission._checkpoint_descriptor(checkpoint_path)
    if manifest_payload is None or training_payload is None:
        _fail("bound manifest/training payload is absent")
    if manifest_descriptor != manifest["file"]:
        _fail("manifest source descriptor drifted from the receipt")
    if training_descriptor != training["file"]:
        _fail("training receipt source descriptor drifted from the receipt")
    if checkpoint_descriptor != checkpoint["file"]:
        _fail("checkpoint source descriptor drifted from the receipt")
    if canonical_digest(manifest_payload) != manifest["canonical_sha256"]:
        _fail("manifest canonical digest drifted from the receipt")
    if checkpoint_descriptor["sha256"] != checkpoint["sha256"]:
        _fail("checkpoint digest drifted from the receipt")

    source_records = _mapping(identity["source_sha256"], "identity.source_sha256")
    if set(source_records) != set(admission.SOURCE_RELATIVE_PATHS):
        _fail("identity.source_sha256 does not cover the complete F3 source set")
    source_digests: dict[str, str] = {}
    for key, relative in admission.SOURCE_RELATIVE_PATHS.items():
        observed = admission._source_descriptor(root, relative, key)
        expected = _mapping(source_records[key], f"identity.source_sha256.{key}")
        if observed != expected:
            _fail(f"{key} source descriptor drifted from the receipt")
        source_digests[key] = str(observed["sha256"])
    return source_digests


def project_authority(
    receipt: Mapping[str, Any],
    *,
    external_authority: Path | str | None,
    resource_admission: Mapping[str, Any] | None,
    source_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    """Project only the non-authorizing envelope after external verification.

    The input mapping is never mutated.  The returned ``projected_receipt``
    is not durable and deliberately cannot be consumed by the runner until a
    producer-issued receipt containing the same bindings is written to the
    reserved namespace.
    """

    original = copy.deepcopy(dict(_mapping(receipt, "source receipt")))
    _receipt_digest(original, "source receipt")
    _validate_identity_digest(original, "source receipt")
    _validate_receipt_shell(original)
    missing = _missing_fields(original)
    non_projectable = tuple(key for key in missing if key not in PROJECTABLE_FIELDS)
    if non_projectable:
        raise ProjectionGap(
            "projection-gap: source receipt lacks current authority-bound schema fields",
            missing_fields=non_projectable,
            blockers=(
                "producer-issued receipt reissue is required; local projection cannot reconstruct "
                + ", ".join(non_projectable),
                "caller/local fields cannot substitute for external scheduler authority",
            ),
        )
    if external_authority is None:
        raise ProjectionGap(
            "projection-gap: external scheduler authority path is required",
            blockers=(
                "no external authority was supplied",
                "caller claim, local receipt field, or GPU probe cannot substitute for authority",
            ),
        )
    if resource_admission is None:
        raise ProjectionGap(
            "projection-gap: externally bound resource snapshot is required",
            blockers=(
                "no scheduler-owned resource snapshot was supplied",
                "legacy/local resource fields cannot authorize projection",
            ),
        )

    identity = _mapping(original["identity"], "identity")
    authority_meta = _mapping(identity["external_authority"], "identity.external_authority")
    authority_path = _absolute(external_authority, "external scheduler authority")
    _exact(authority_meta, "path", str(authority_path), "identity.external_authority")
    try:
        resource_snapshot = admission._validate_resource(resource_admission)
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        raise ProjectionGap(
            "projection-gap: supplied resource snapshot is not admissible",
            blockers=(str(error),),
        ) from error
    identity_resource = _mapping(identity["resource_snapshot"], "identity.resource_snapshot")
    if canonical_json(resource_snapshot) != canonical_json(dict(identity_resource)):
        _fail("supplied resource snapshot is not exactly the receipt-bound resource snapshot")

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
        )
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        raise ProjectionGap(
            "projection-gap: receipt nonce/namespace plan cannot be rebound",
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
    if canonical_json(current_namespace) != canonical_json(dict(namespace_descriptor)):
        _fail("namespace descriptor drifted before authority projection")

    projected = copy.deepcopy(original)
    projected["authority"] = _authority_envelope()
    projected.pop("receipt_file", None)
    projected.pop("receipt_sha256", None)
    projected["receipt_sha256"] = canonical_digest(projected)
    projection_bindings = {
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
        "source_receipt_sha256": source_receipt_sha256 or str(original["receipt_sha256"]),
        "projected_receipt": projected,
        "authority": dict(projected["authority"]),
        "external_authority": external_meta,
        "bindings": projection_bindings,
        "durable_receipt_written": False,
        "runner_consumable": False,
        "historical_receipt_rewritten": False,
        "popen_allowed": False,
        "formal_promotion_allowed": False,
        **ZERO_CREDIT,
    }


def build_report(
    receipt_path: Path | str,
    *,
    external_authority: Path | str | None = None,
    resource_admission: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        receipt, file_info = _read_receipt(receipt_path)
        gap = describe_receipt_gap(receipt_path)
        missing = tuple(gap["missing_fields"])
        non_projectable = tuple(gap["non_projectable_missing_fields"])
        if non_projectable:
            raise ProjectionGap(
                "projection-gap: current receipt requires producer reissue",
                missing_fields=non_projectable,
                blockers=tuple(gap["blockers"]),
            )
        result = project_authority(
            receipt,
            external_authority=external_authority,
            resource_admission=resource_admission,
            source_receipt_sha256=str(receipt["receipt_sha256"]),
        )
        return {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "authority_projection_ready",
            "source_receipt": file_info,
            "projection": {
                key: value
                for key, value in result.items()
                if key != "projected_receipt"
            },
            "missing_fields": list(missing),
            "historical_receipt_rewritten": False,
            "durable_receipt_written": False,
            "runner_consumable": False,
            "popen_allowed": False,
            "side_effects": _side_effects(),
            **ZERO_CREDIT,
        }
    except ProjectionGap as error:
        try:
            gap = describe_receipt_gap(receipt_path)
        except Exception:
            gap = {
                "source_receipt": {"path": str(receipt_path)},
                "missing_fields": list(error.missing_fields),
                "projectable_missing_fields": [],
                "non_projectable_missing_fields": list(error.missing_fields),
                "blockers": [],
            }
        blockers = list(dict.fromkeys([*gap.get("blockers", []), *error.blockers, str(error)]))
        return {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_projection_gap",
            "source_receipt": gap.get("source_receipt", {"path": str(receipt_path)}),
            "source_receipt_schema": gap.get("source_receipt_schema"),
            "source_receipt_sha256": gap.get("source_receipt_sha256"),
            "missing_fields": list(gap.get("missing_fields", error.missing_fields)),
            "projectable_missing_fields": list(gap.get("projectable_missing_fields", [])),
            "non_projectable_missing_fields": list(
                gap.get("non_projectable_missing_fields", error.missing_fields)
            ),
            "external_authority": {
                "path_supplied": external_authority is not None,
                "verified": False,
                "real_external_document_required": True,
            },
            "resource_binding": {
                "supplied": resource_admission is not None,
                "verified": False,
            },
            "blockers": blockers,
            "historical_receipt_rewritten": False,
            "durable_receipt_written": False,
            "runner_consumable": False,
            "popen_allowed": False,
            "side_effects": _side_effects(),
            **ZERO_CREDIT,
        }
    except (ProjectionError, admission.AdmissionError, OSError, TypeError, ValueError) as error:
        return {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_projection_gap",
            "source_receipt": {"path": str(receipt_path)},
            "missing_fields": [],
            "projectable_missing_fields": [],
            "non_projectable_missing_fields": [],
            "external_authority": {
                "path_supplied": external_authority is not None,
                "verified": False,
                "real_external_document_required": True,
            },
            "resource_binding": {
                "supplied": resource_admission is not None,
                "verified": False,
            },
            "blockers": [str(error)],
            "historical_receipt_rewritten": False,
            "durable_receipt_written": False,
            "runner_consumable": False,
            "popen_allowed": False,
            "side_effects": _side_effects(),
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


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        if report.get("status") not in {"blocked_projection_gap", "authority_projection_ready"}:
            _fail("report.status is not a projection status")
        _validate_zero_credit(report, "report")
        effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key, expected in _side_effects().items():
            _exact(effects, key, expected, "report.side_effects")
        _exact(report, "historical_receipt_rewritten", False, "report")
        _exact(report, "durable_receipt_written", False, "report")
        _exact(report, "runner_consumable", False, "report")
        _exact(report, "popen_allowed", False, "report")
    except (ProjectionError, TypeError, ValueError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    blockers = report.get("blockers", [])
    lines = [
        "# F3 graph_raw hidden16 seed17 authority projection",
        "",
        f"- status: `{report.get('status')}`",
        f"- source receipt: `{report.get('source_receipt', {}).get('path')}`",
        f"- source receipt SHA-256: `{report.get('source_receipt_sha256')}`",
        f"- Popen allowed: `{report.get('popen_allowed')}`",
        f"- durable receipt written: `{report.get('durable_receipt_written')}`",
        f"- historical receipt rewritten: `{report.get('historical_receipt_rewritten')}`",
        f"- credit: `{report.get('credit')}`",
        "",
        "## Projection boundary",
        "",
        "This adapter accepts only an externally signed scheduler document and "
        "exact nonce/namespace/source/resource bindings. It never treats a "
        "caller claim as authority and never mints execution capability.",
        "",
        "## Missing or blocking fields",
        "",
    ]
    for item in report.get("missing_fields", []):
        lines.append(f"- `{item}`")
    if not report.get("missing_fields"):
        lines.append("- none")
    lines.extend(["", "## Blockers", ""])
    for blocker in blockers:
        lines.append(f"- {blocker}")
    if not blockers:
        lines.append("- none")
    lines.extend(
        [
            "",
            "No Popen/solver/worker/GPU/queue execution occurs. The projection "
            "is diagnostic-only and zero-credit.",
            "",
        ]
    )
    return "\n".join(lines)


def _load_resource(path: Path | str) -> Mapping[str, Any]:
    candidate = _absolute(path, "resource admission JSON")
    try:
        _raw, _descriptor, payload = admission._read_file(
            candidate,
            "resource admission JSON",
            max_bytes=256 * 1024,
            parse_json=True,
        )
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        _fail(str(error))
    return _mapping(payload, "resource admission JSON")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--external-authority", type=Path, default=None)
    parser.add_argument("--resource-admission", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--verify-report", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.verify_report is not None:
        try:
            report = json.loads(args.verify_report.read_text(encoding="utf-8"))
            errors = validate_report(_mapping(report, "report"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            print(f"invalid projection report: {error}", file=sys.stderr)
            return 2
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 2
        return 0

    if args.receipt is None:
        print("--receipt is required unless --verify-report is used", file=sys.stderr)
        return 2

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
