#!/usr/bin/env python3
"""Audit the next bounded A8 independent-reproduction boundary.

This contract is deliberately synthetic-only and non-authorizing.  It binds
four typed projections through one canonical identity:

* a distinct source/reproduction data-root projection;
* a trusted-root review placeholder;
* an external-host attestation placeholder; and
* a non-diagnostic full-product receipt placeholder.

The fixture carries no trusted review, no external-host attestation, and no
non-diagnostic full-product receipt.  A structurally valid fixture therefore
returns a blocked, fail-closed report.  This module never treats a caller
boolean as attestation, opens production data, probes a host, starts a native
solver/worker/GPU/queue, or mutates Core state.  It is a bounded diagnostic
contract only: readiness and independent-reproduction claims remain false and
credit remains zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "core.reproduction.a8_trusted_root_external_host_attestation_input.v1"
REPORT_SCHEMA = "core.reproduction.a8_trusted_root_external_host_attestation_report.v1"
DATA_ROOT_SCHEMA = "core.reproduction.a8_distinct_data_root_identity.v1"
TRUSTED_ROOT_SCHEMA = "core.reproduction.a8_trusted_root_review.v1"
EXTERNAL_HOST_SCHEMA = "core.reproduction.a8_external_host_attestation.v1"
FULL_PRODUCT_SCHEMA = "core.reproduction.a8_non_diagnostic_full_product_receipt.v1"
STRUCTURAL_BLOCKED_STATUS = (
    "blocked_missing_trusted_root_external_host_and_"
    "non_diagnostic_full_product_receipt"
)
INVALID_BLOCKED_STATUS = "blocked_invalid_or_untrusted_projection"
INPUT_ORIGIN = "synthetic_fixture"
MAX_INPUT_BYTES = 128 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)

INPUT_FIELDS = frozenset({
    "schema",
    "input_origin",
    "diagnostic_only",
    "data_root_identity",
    "trusted_root_review",
    "external_host_attestation",
    "full_product_receipt",
})
DATA_ROOT_FIELDS = frozenset({
    "schema",
    "source_host_id",
    "reproduction_host_id",
    "source_data_root",
    "reproduction_data_root",
    "distinct_physical_hosts",
    "distinct_roots",
    "package_sha256",
    "source_manifest_sha256",
    "reproduction_manifest_sha256",
    "source_identity_sha256",
    "reproduction_identity_sha256",
    "manifest_binding_verified",
    "cross_binding_sha256",
    "input_origin",
    "diagnostic_only",
})
TRUSTED_ROOT_FIELDS = frozenset({
    "schema",
    "review_id",
    "root_id",
    "authority_scope",
    "source_host_id",
    "source_data_root",
    "source_identity_sha256",
    "decision",
    "authenticated",
    "receipt_present",
    "review_receipt_sha256",
    "cross_binding_sha256",
    "input_origin",
    "diagnostic_only",
})
EXTERNAL_HOST_FIELDS = frozenset({
    "schema",
    "attestation_id",
    "role",
    "host_id",
    "hostname",
    "reproduction_data_root",
    "reproduction_identity_sha256",
    "trusted_root_review_id",
    "attested",
    "receipt_present",
    "attestation_receipt_sha256",
    "cross_binding_sha256",
    "input_origin",
    "diagnostic_only",
})
FULL_PRODUCT_FIELDS = frozenset({
    "schema",
    "receipt_id",
    "product_scope",
    "execution_status",
    "source_data_root",
    "reproduction_data_root",
    "source_identity_sha256",
    "reproduction_identity_sha256",
    "trusted_root_review_id",
    "external_host_attestation_id",
    "receipt_present",
    "non_diagnostic",
    "full_product",
    "receipt_sha256",
    "cross_binding_sha256",
    "input_origin",
    "diagnostic_only",
})

FALSE_CLAIMS = {
    "readiness_pass": False,
    "independent_reproduction": False,
    "full_product_reproduction": False,
    "formal_admission": False,
    "formal_training": False,
    "credit": 0,
    "qualification_credit": 0,
}
ZERO_MUTATIONS = {
    "registry": 0,
    "ledger": 0,
    "denominator": 0,
    "gate": 0,
    "completion": 0,
}
EXECUTION_CONSTRAINTS = {
    "read_only": True,
    "synthetic_projection_only": True,
    "production_data_opened": False,
    "host_probe_performed": False,
    "trusted_root_authenticated": False,
    "external_host_attested": False,
    "native_started": False,
    "solver_started": False,
    "worker_started": False,
    "gpu_started": False,
    "queue_mutation": 0,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "completion_mutation": 0,
}


class ContractError(ValueError):
    """A bounded cross-binding contract violation."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ContractError(code, message)


def canonical_json_bytes(value: Any, *, label: str = "value") -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise ContractError("NON_CANONICAL_JSON", f"{label} is not canonical JSON") from error


def sha256_json(value: Any, *, label: str = "value") -> str:
    return hashlib.sha256(canonical_json_bytes(value, label=label)).hexdigest()


def _exact(value: Any, fields: frozenset[str], *, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "OBJECT_REQUIRED", f"{label} must be an object")
    _require(set(value) == fields, "FIELDS_NOT_EXACT", f"{label} fields are not exact")
    return value


def _sha(value: Any, *, label: str) -> str:
    _require(type(value) is str and SHA256_RE.fullmatch(value) is not None,
             "SHA256_INVALID", f"{label} is not a lowercase SHA-256")
    return value


def _text(value: Any, *, label: str) -> str:
    _require(type(value) is str and bool(value.strip()),
             "TEXT_MISSING", f"{label} must be a non-empty string")
    return value.strip()


def _root(value: Any, *, label: str) -> str:
    raw = _text(value, label=label)
    _require(raw.startswith("/") and "\\" not in raw,
             "DATA_ROOT_INVALID", f"{label} must be an absolute POSIX root")
    parts = raw.split("/")
    _require(".." not in parts, "DATA_ROOT_INVALID", f"{label} contains '..'")
    normalized = posixpath.normpath(raw)
    _require(normalized.startswith("/") and normalized != ".",
             "DATA_ROOT_INVALID", f"{label} cannot be canonicalized")
    return normalized


def _diagnostic_markers(value: Mapping[str, Any], *, label: str) -> None:
    _require(value.get("input_origin") == INPUT_ORIGIN,
             "INPUT_ORIGIN_INVALID", f"{label} is not a synthetic fixture")
    _require(value.get("diagnostic_only") is True,
             "DIAGNOSTIC_MARKER_MISSING", f"{label} is not diagnostic-only")


def _identity_hash(host_id: str, data_root: str, manifest_sha256: str,
                  package_sha256: str) -> str:
    return sha256_json({
        "host_id": host_id,
        "data_root": data_root,
        "manifest_sha256": manifest_sha256,
        "package_sha256": package_sha256,
    }, label="data-root identity")


def _cross_binding_hash(context: Mapping[str, str]) -> str:
    return sha256_json({
        "source_host_id": context["source_host_id"],
        "reproduction_host_id": context["reproduction_host_id"],
        "source_data_root": context["source_data_root"],
        "reproduction_data_root": context["reproduction_data_root"],
        "source_identity_sha256": context["source_identity_sha256"],
        "reproduction_identity_sha256": context["reproduction_identity_sha256"],
        "trusted_root_review_id": context["trusted_root_review_id"],
        "root_id": context["root_id"],
        "external_host_attestation_id": context["external_host_attestation_id"],
        "full_product_receipt_id": context["full_product_receipt_id"],
    }, label="A8 cross-binding identity")


def _validate_data_roots(value: Any) -> dict[str, Any]:
    row = _exact(value, DATA_ROOT_FIELDS, label="distinct data-root identity")
    _require(row["schema"] == DATA_ROOT_SCHEMA,
             "DATA_ROOT_SCHEMA_MISMATCH", "data-root identity schema is unsupported")
    _diagnostic_markers(row, label="distinct data-root identity")

    source_host = _text(row["source_host_id"], label="source_host_id")
    reproduction_host = _text(row["reproduction_host_id"], label="reproduction_host_id")
    _require(row["distinct_physical_hosts"] is True,
             "DISTINCT_HOSTS_NOT_ASSERTED", "distinct physical hosts are not asserted")
    _require(source_host != reproduction_host, "HOSTS_NOT_DISTINCT",
             "source and reproduction host ids are identical")

    source_root = _root(row["source_data_root"], label="source_data_root")
    reproduction_root = _root(row["reproduction_data_root"], label="reproduction_data_root")
    _require(row["distinct_roots"] is True, "DISTINCT_ROOTS_NOT_ASSERTED",
             "distinct data roots are not asserted")
    _require(source_root != reproduction_root, "DATA_ROOTS_NOT_DISTINCT",
             "source and reproduction data roots are identical")

    package_sha = _sha(row["package_sha256"], label="package_sha256")
    source_manifest = _sha(row["source_manifest_sha256"], label="source_manifest_sha256")
    reproduction_manifest = _sha(
        row["reproduction_manifest_sha256"], label="reproduction_manifest_sha256"
    )
    _require(source_manifest != reproduction_manifest,
             "MANIFESTS_NOT_DISTINCT", "source and reproduction manifests are identical")
    expected_source = _identity_hash(source_host, source_root, source_manifest, package_sha)
    expected_reproduction = _identity_hash(
        reproduction_host, reproduction_root, reproduction_manifest, package_sha
    )
    _require(row["source_identity_sha256"] == expected_source
             and row["reproduction_identity_sha256"] == expected_reproduction,
             "DATA_ROOT_IDENTITY_HASH_MISMATCH",
             "data-root identities do not bind host, root, manifest and package")
    _require(row["manifest_binding_verified"] is True,
             "MANIFEST_BINDING_NOT_VERIFIED",
             "data-root projection does not assert manifest binding")
    _sha(row["cross_binding_sha256"], label="data-root cross_binding_sha256")
    return {
        "source_host_id": source_host,
        "reproduction_host_id": reproduction_host,
        "source_data_root": source_root,
        "reproduction_data_root": reproduction_root,
        "source_identity_sha256": expected_source,
        "reproduction_identity_sha256": expected_reproduction,
        "package_sha256": package_sha,
        "source_manifest_sha256": source_manifest,
        "reproduction_manifest_sha256": reproduction_manifest,
        "cross_binding_sha256": row["cross_binding_sha256"],
    }


def _validate_trusted_root(value: Any, *, roots: Mapping[str, Any]) -> dict[str, Any]:
    row = _exact(value, TRUSTED_ROOT_FIELDS, label="trusted-root review")
    _require(row["schema"] == TRUSTED_ROOT_SCHEMA,
             "TRUSTED_ROOT_SCHEMA_MISMATCH", "trusted-root review schema is unsupported")
    _diagnostic_markers(row, label="trusted-root review")
    review_id = _text(row["review_id"], label="trusted-root review_id")
    root_id = _text(row["root_id"], label="trusted-root root_id")
    _text(row["authority_scope"], label="trusted-root authority_scope")
    _require(row["source_host_id"] == roots["source_host_id"],
             "TRUSTED_ROOT_HOST_MISMATCH", "trusted-root review is not bound to source host")
    _require(_root(row["source_data_root"], label="trusted-root source_data_root")
             == roots["source_data_root"],
             "TRUSTED_ROOT_ROOT_MISMATCH", "trusted-root review is not bound to source root")
    _require(row["source_identity_sha256"] == roots["source_identity_sha256"],
             "TRUSTED_ROOT_IDENTITY_MISMATCH",
             "trusted-root review is not bound to source identity")
    _require(row["decision"] == "not_attested"
             and row["authenticated"] is False
             and row["receipt_present"] is False
             and row["review_receipt_sha256"] is None,
             "TRUSTED_ROOT_CLAIM_FORBIDDEN",
             "synthetic input cannot claim or carry a trusted-root attestation")
    _sha(row["cross_binding_sha256"], label="trusted-root cross_binding_sha256")
    return {
        "review_id": review_id,
        "root_id": root_id,
        "authenticated": False,
        "cross_binding_sha256": row["cross_binding_sha256"],
    }


def _validate_external_host(value: Any, *, roots: Mapping[str, Any],
                            trusted_root: Mapping[str, Any]) -> dict[str, Any]:
    row = _exact(value, EXTERNAL_HOST_FIELDS, label="external-host attestation")
    _require(row["schema"] == EXTERNAL_HOST_SCHEMA,
             "EXTERNAL_HOST_SCHEMA_MISMATCH",
             "external-host attestation schema is unsupported")
    _diagnostic_markers(row, label="external-host attestation")
    attestation_id = _text(row["attestation_id"], label="external-host attestation_id")
    _require(row["role"] == "reproduction_host", "EXTERNAL_HOST_ROLE_MISMATCH",
             "external-host attestation must describe reproduction_host")
    _require(row["host_id"] == roots["reproduction_host_id"],
             "EXTERNAL_HOST_ID_MISMATCH",
             "external-host attestation is not bound to reproduction host")
    _text(row["hostname"], label="external-host hostname")
    _require(_root(row["reproduction_data_root"], label="external-host reproduction_data_root")
             == roots["reproduction_data_root"],
             "EXTERNAL_HOST_ROOT_MISMATCH",
             "external-host attestation is not bound to reproduction root")
    _require(row["reproduction_identity_sha256"] == roots["reproduction_identity_sha256"],
             "EXTERNAL_HOST_IDENTITY_MISMATCH",
             "external-host attestation is not bound to reproduction identity")
    _require(row["trusted_root_review_id"] == trusted_root["review_id"],
             "EXTERNAL_HOST_ROOT_REVIEW_MISMATCH",
             "external-host attestation is not bound to trusted-root review")
    _require(row["attested"] is False
             and row["receipt_present"] is False
             and row["attestation_receipt_sha256"] is None,
             "EXTERNAL_HOST_CLAIM_FORBIDDEN",
             "synthetic input cannot claim or carry an external-host attestation")
    _sha(row["cross_binding_sha256"], label="external-host cross_binding_sha256")
    return {
        "attestation_id": attestation_id,
        "attested": False,
        "cross_binding_sha256": row["cross_binding_sha256"],
    }


def _validate_full_product(value: Any, *, roots: Mapping[str, Any],
                           trusted_root: Mapping[str, Any],
                           external_host: Mapping[str, Any]) -> dict[str, Any]:
    row = _exact(value, FULL_PRODUCT_FIELDS,
                 label="non-diagnostic full-product receipt")
    _require(row["schema"] == FULL_PRODUCT_SCHEMA,
             "FULL_PRODUCT_SCHEMA_MISMATCH",
             "full-product receipt schema is unsupported")
    _diagnostic_markers(row, label="non-diagnostic full-product receipt")
    receipt_id = _text(row["receipt_id"], label="full-product receipt_id")
    _text(row["product_scope"], label="full-product product_scope")
    _require(row["source_data_root"] == roots["source_data_root"]
             and row["reproduction_data_root"] == roots["reproduction_data_root"],
             "FULL_PRODUCT_ROOT_MISMATCH",
             "full-product receipt is not bound to both data roots")
    _require(row["source_identity_sha256"] == roots["source_identity_sha256"]
             and row["reproduction_identity_sha256"] == roots["reproduction_identity_sha256"],
             "FULL_PRODUCT_IDENTITY_MISMATCH",
             "full-product receipt is not bound to both data-root identities")
    _require(row["trusted_root_review_id"] == trusted_root["review_id"],
             "FULL_PRODUCT_ROOT_REVIEW_MISMATCH",
             "full-product receipt is not bound to trusted-root review")
    _require(row["external_host_attestation_id"] == external_host["attestation_id"],
             "FULL_PRODUCT_HOST_ATTESTATION_MISMATCH",
             "full-product receipt is not bound to external-host attestation")
    _require(row["execution_status"] == "not_present"
             and row["receipt_present"] is False
             and row["non_diagnostic"] is False
             and row["full_product"] is False
             and row["receipt_sha256"] is None,
             "FULL_PRODUCT_CLAIM_FORBIDDEN",
             "synthetic input cannot claim or carry a non-diagnostic full-product receipt")
    _sha(row["cross_binding_sha256"], label="full-product cross_binding_sha256")
    return {
        "receipt_id": receipt_id,
        "non_diagnostic": False,
        "full_product": False,
        "cross_binding_sha256": row["cross_binding_sha256"],
    }


def _base_report() -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "status": "blocked",
        "passed": False,
        "structural_contract_passed": False,
        **FALSE_CLAIMS,
        "diagnostic_only": True,
        "execution_constraints": dict(EXECUTION_CONSTRAINTS),
        "mutations": dict(ZERO_MUTATIONS),
        "checks": {
            "distinct_data_root_identity": False,
            "trusted_root_review_cross_binding": False,
            "external_host_attestation_cross_binding": False,
            "non_diagnostic_full_product_receipt_cross_binding": False,
            "cross_binding_identity": False,
            "trusted_root_review": False,
            "external_host_attestation": False,
            "non_diagnostic_full_product_receipt": False,
        },
        "bindings": None,
        "blockers": [],
        "errors": [],
        "interpretation": (
            "Synthetic bounded cross-binding contract only; identity binding is not trusted "
            "attestation and cannot admit independent reproduction or issue credit."
        ),
    }


def build_report(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one synthetic projection and return a non-authorizing report."""
    report = _base_report()
    try:
        root = _exact(projection, INPUT_FIELDS, label="A8 attestation projection")
        _require(root["schema"] == SCHEMA, "INPUT_SCHEMA_MISMATCH",
                 "A8 attestation projection schema is unsupported")
        _require(root["input_origin"] == INPUT_ORIGIN,
                 "INPUT_ORIGIN_INVALID", "A8 attestation projection is not synthetic_fixture")
        _require(root["diagnostic_only"] is True,
                 "DIAGNOSTIC_MARKER_MISSING",
                 "A8 attestation projection is not diagnostic-only")

        roots = _validate_data_roots(root["data_root_identity"])
        trusted_root = _validate_trusted_root(root["trusted_root_review"], roots=roots)
        external_host = _validate_external_host(
            root["external_host_attestation"], roots=roots, trusted_root=trusted_root
        )
        full_product = _validate_full_product(
            root["full_product_receipt"],
            roots=roots,
            trusted_root=trusted_root,
            external_host=external_host,
        )
        context = {
            **roots,
            "trusted_root_review_id": trusted_root["review_id"],
            "root_id": trusted_root["root_id"],
            "external_host_attestation_id": external_host["attestation_id"],
            "full_product_receipt_id": full_product["receipt_id"],
        }
        expected_binding = _cross_binding_hash(context)
        _require(
            all(item["cross_binding_sha256"] == expected_binding for item in
                (roots, trusted_root, external_host, full_product)),
            "CROSS_BINDING_HASH_MISMATCH",
            "typed projections do not share one canonical cross-binding identity",
        )

        report.update({
            "status": STRUCTURAL_BLOCKED_STATUS,
            "passed": True,
            "structural_contract_passed": True,
            "checks": {
                "distinct_data_root_identity": True,
                "trusted_root_review_cross_binding": True,
                "external_host_attestation_cross_binding": True,
                "non_diagnostic_full_product_receipt_cross_binding": True,
                "cross_binding_identity": True,
                "trusted_root_review": False,
                "external_host_attestation": False,
                "non_diagnostic_full_product_receipt": False,
            },
            "bindings": {
                "source_host_id": roots["source_host_id"],
                "reproduction_host_id": roots["reproduction_host_id"],
                "source_data_root": roots["source_data_root"],
                "reproduction_data_root": roots["reproduction_data_root"],
                "source_identity_sha256": roots["source_identity_sha256"],
                "reproduction_identity_sha256": roots["reproduction_identity_sha256"],
                "trusted_root_review_id": trusted_root["review_id"],
                "root_id": trusted_root["root_id"],
                "external_host_attestation_id": external_host["attestation_id"],
                "full_product_receipt_id": full_product["receipt_id"],
                "cross_binding_sha256": expected_binding,
                "trusted_root_authenticated": False,
                "external_host_attested": False,
                "full_product_receipt_present": False,
            },
            "blockers": [
                "trusted_root_review_not_attested",
                "external_host_attestation_not_attested",
                "non_diagnostic_full_product_receipt_missing",
                "synthetic_cross_binding_is_identity_only_not_evidence",
            ],
            "next_required": [
                "obtain a real independently trusted root review receipt",
                "obtain a real external-host attestation bound to the reproduction host and root",
                "obtain a real non-diagnostic full-product receipt bound to both attestations",
                "re-run the Core independent_reproduction gate verifier",
            ],
        })
    except ContractError as error:
        report["status"] = INVALID_BLOCKED_STATUS
        report["errors"] = [{"code": error.code, "message": str(error)}]
        report["blockers"] = ["invalid_or_untrusted_cross_binding_projection"]
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for a generated diagnostic report."""
    errors: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("report.schema mismatch")
    if report.get("diagnostic_only") is not True:
        errors.append("report.diagnostic_only must be true")
    for key, expected in FALSE_CLAIMS.items():
        if report.get(key) != expected:
            errors.append(f"report.{key} must remain {expected!r}")
    if report.get("mutations") != ZERO_MUTATIONS:
        errors.append("report.mutations must remain zero")
    if report.get("execution_constraints") != EXECUTION_CONSTRAINTS:
        errors.append("report.execution_constraints drift")
    checks = report.get("checks")
    if not isinstance(checks, Mapping):
        errors.append("report.checks missing")
    else:
        for key in (
            "trusted_root_review",
            "external_host_attestation",
            "non_diagnostic_full_product_receipt",
        ):
            if checks.get(key) is not False:
                errors.append(f"report.checks.{key} must remain false")
    status = report.get("status")
    if status == STRUCTURAL_BLOCKED_STATUS:
        if report.get("passed") is not True:
            errors.append("structural blocked report.passed must be true")
        if report.get("passed") is not True or report.get("structural_contract_passed") is not True:
            errors.append("blocked structural report must retain structural_contract_passed")
        expected_checks = {
            "distinct_data_root_identity": True,
            "trusted_root_review_cross_binding": True,
            "external_host_attestation_cross_binding": True,
            "non_diagnostic_full_product_receipt_cross_binding": True,
            "cross_binding_identity": True,
            "trusted_root_review": False,
            "external_host_attestation": False,
            "non_diagnostic_full_product_receipt": False,
        }
        if isinstance(checks, Mapping):
            if dict(checks) != expected_checks:
                errors.append("structural blocked report.checks drift")
            for key in (
                "distinct_data_root_identity",
                "trusted_root_review_cross_binding",
                "external_host_attestation_cross_binding",
                "non_diagnostic_full_product_receipt_cross_binding",
                "cross_binding_identity",
            ):
                if checks.get(key) is not True:
                    errors.append(f"report.checks.{key} must be true for synthetic fixture")
    elif status == INVALID_BLOCKED_STATUS:
        if report.get("passed") is not False:
            errors.append("invalid blocked report.passed must be false")
        if report.get("structural_contract_passed") is not False:
            errors.append("invalid blocked report must not be structurally passed")
        if not isinstance(report.get("errors"), list) or not report["errors"]:
            errors.append("invalid blocked report.errors must be non-empty")
    else:
        errors.append("report.status is unsupported")
    if report.get("readiness_pass") is not False:
        errors.append("report.readiness_pass must remain false")
    return errors


def synthetic_projection() -> dict[str, Any]:
    """Return the bounded fixture used for the non-authorizing report."""
    source_host = "synthetic-source-host"
    reproduction_host = "synthetic-reproduction-host"
    source_root = "/synthetic/core/source-root"
    reproduction_root = "/synthetic/core/reproduction-root"
    package_sha = "a" * 64
    source_manifest = "b" * 64
    reproduction_manifest = "c" * 64
    source_identity = _identity_hash(source_host, source_root, source_manifest, package_sha)
    reproduction_identity = _identity_hash(
        reproduction_host, reproduction_root, reproduction_manifest, package_sha
    )
    trusted_root_review_id = "synthetic-trusted-root-review-missing-v2"
    root_id = "synthetic-root-not-authority-v2"
    external_host_attestation_id = "synthetic-external-host-attestation-missing-v2"
    full_product_receipt_id = "synthetic-full-product-receipt-missing-v2"
    context = {
        "source_host_id": source_host,
        "reproduction_host_id": reproduction_host,
        "source_data_root": source_root,
        "reproduction_data_root": reproduction_root,
        "source_identity_sha256": source_identity,
        "reproduction_identity_sha256": reproduction_identity,
        "trusted_root_review_id": trusted_root_review_id,
        "root_id": root_id,
        "external_host_attestation_id": external_host_attestation_id,
        "full_product_receipt_id": full_product_receipt_id,
    }
    cross_binding = _cross_binding_hash(context)
    return {
        "schema": SCHEMA,
        "input_origin": INPUT_ORIGIN,
        "diagnostic_only": True,
        "data_root_identity": {
            "schema": DATA_ROOT_SCHEMA,
            "source_host_id": source_host,
            "reproduction_host_id": reproduction_host,
            "source_data_root": source_root,
            "reproduction_data_root": reproduction_root,
            "distinct_physical_hosts": True,
            "distinct_roots": True,
            "package_sha256": package_sha,
            "source_manifest_sha256": source_manifest,
            "reproduction_manifest_sha256": reproduction_manifest,
            "source_identity_sha256": source_identity,
            "reproduction_identity_sha256": reproduction_identity,
            "manifest_binding_verified": True,
            "cross_binding_sha256": cross_binding,
            "input_origin": INPUT_ORIGIN,
            "diagnostic_only": True,
        },
        "trusted_root_review": {
            "schema": TRUSTED_ROOT_SCHEMA,
            "review_id": trusted_root_review_id,
            "root_id": root_id,
            "authority_scope": "core.independent_reproduction",
            "source_host_id": source_host,
            "source_data_root": source_root,
            "source_identity_sha256": source_identity,
            "decision": "not_attested",
            "authenticated": False,
            "receipt_present": False,
            "review_receipt_sha256": None,
            "cross_binding_sha256": cross_binding,
            "input_origin": INPUT_ORIGIN,
            "diagnostic_only": True,
        },
        "external_host_attestation": {
            "schema": EXTERNAL_HOST_SCHEMA,
            "attestation_id": external_host_attestation_id,
            "role": "reproduction_host",
            "host_id": reproduction_host,
            "hostname": reproduction_host,
            "reproduction_data_root": reproduction_root,
            "reproduction_identity_sha256": reproduction_identity,
            "trusted_root_review_id": trusted_root_review_id,
            "attested": False,
            "receipt_present": False,
            "attestation_receipt_sha256": None,
            "cross_binding_sha256": cross_binding,
            "input_origin": INPUT_ORIGIN,
            "diagnostic_only": True,
        },
        "full_product_receipt": {
            "schema": FULL_PRODUCT_SCHEMA,
            "receipt_id": full_product_receipt_id,
            "product_scope": "core.full_product_reproduction",
            "execution_status": "not_present",
            "source_data_root": source_root,
            "reproduction_data_root": reproduction_root,
            "source_identity_sha256": source_identity,
            "reproduction_identity_sha256": reproduction_identity,
            "trusted_root_review_id": trusted_root_review_id,
            "external_host_attestation_id": external_host_attestation_id,
            "receipt_present": False,
            "non_diagnostic": False,
            "full_product": False,
            "receipt_sha256": None,
            "cross_binding_sha256": cross_binding,
            "input_origin": INPUT_ORIGIN,
            "diagnostic_only": True,
        },
    }


def _read_projection(path: Path) -> Mapping[str, Any]:
    raw = path.read_bytes()
    _require(0 < len(raw) <= MAX_INPUT_BYTES, "INPUT_SIZE_OUT_OF_BOUNDS",
             "A8 attestation projection exceeds bounded JSON input limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError("INVALID_INPUT_JSON", "A8 attestation projection is not valid JSON") from error
    _require(isinstance(value, Mapping), "INPUT_OBJECT_REQUIRED",
             "A8 attestation projection must be a JSON object")
    return value


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit")
    source = audit.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--synthetic", action="store_true")
    audit.add_argument("--output", required=True, type=Path)
    validate = sub.add_parser("validate")
    validate.add_argument("--report", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "audit":
        try:
            projection = synthetic_projection() if args.synthetic else _read_projection(args.input)
            report = build_report(projection)
        except (OSError, ContractError) as error:
            report = _base_report()
            report["status"] = "blocked_invalid_or_untrusted_projection"
            report["errors"] = [{"code": getattr(error, "code", "INPUT_ERROR"),
                                 "message": str(error)}]
            report["blockers"] = ["invalid_or_untrusted_cross_binding_projection"]
        write_json(args.output, report)
        return 0
    report = json.loads(args.report.read_text(encoding="utf-8"))
    errors = validate_report(report)
    if errors:
        for error in errors:
            print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
