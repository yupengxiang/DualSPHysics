#!/usr/bin/env python3
"""Audit the missing A8 full-product/external-host/root join.

The A8 package verifier already binds a reader, an autonomous prediction, and
scoring to one synthetic package.  The A8 trusted-root/external-host contract
already binds distinct source/reproduction identities to diagnostic
attestation placeholders.  Neither contract, by itself, proves that those
two projections describe the same package run and the same
reader/prediction/scoring chain.

This module is the additive join boundary for that gap.  It accepts only one
bounded synthetic projection and requires a canonical identity shared by:

* the package-level manifest/receipt/artifact-chain projection;
* the distinct source/reproduction data-root projection;
* the trusted-root review placeholder;
* the external-host attestation placeholder; and
* the full-product join receipt placeholder.

The result is structural diagnostic evidence only.  Synthetic caller fields
can never authenticate a root, attest a host, establish independent
reproduction, provide a terminal full-product receipt, or mint credit.
Unknown fields are rejected and no production payload is opened.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_independent_reproduction_secure_io_v1 import (
    SecureReadError,
    read_bounded_json_object,
)


SCHEMA = "core.reproduction.a8_full_product_external_host_root_join_gap_input.v1"
REPORT_SCHEMA = "core.reproduction.a8_full_product_external_host_root_join_gap_report.v1"
PACKAGE_SCHEMA = "core.a8.full_product_receipt_manifest_verify_report.v1"
DATA_ROOT_SCHEMA = "core.reproduction.a8_distinct_data_root_identity.v1"
TRUSTED_ROOT_SCHEMA = "core.reproduction.a8_trusted_root_review.v1"
EXTERNAL_HOST_SCHEMA = "core.reproduction.a8_external_host_attestation.v1"
JOIN_SCHEMA = "core.reproduction.a8_full_product_external_host_root_join.v1"
INPUT_ORIGIN = "synthetic_fixture"
MAX_INPUT_BYTES = 128 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
ROLES = ("reader", "prediction", "scoring")

INPUT_FIELDS = frozenset({
    "schema",
    "input_origin",
    "diagnostic_only",
    "package_boundary",
    "data_root_identity",
    "trusted_root_review",
    "external_host_attestation",
    "full_product_join_receipt",
})
IDENTITY_FIELDS = frozenset({
    "host_id",
    "physical_host_id",
    "data_root",
    "identity_sha256",
})
ARTIFACT_FIELDS = frozenset(ROLES)
CHAIN_FIELDS = frozenset({
    "reader_artifact_sha256",
    "prediction_reader_input_sha256",
    "prediction_artifact_sha256",
    "scoring_reader_input_sha256",
    "scoring_prediction_input_sha256",
    "scoring_artifact_sha256",
})
PACKAGE_FIELDS = frozenset({
    "schema",
    "status",
    "package_binding_verified",
    "package_id",
    "case_id",
    "attempt_id",
    "nonce",
    "package_sha256",
    "manifest_sha256",
    "receipt_sha256",
    "source",
    "reproduction",
    "artifact_digests",
    "chain",
    "artifact_chain_sha256",
    "cross_binding_sha256",
    "input_origin",
    "diagnostic_only",
    "full_product_reproduction",
    "independent_reproduction",
    "checkpoint",
    "credit",
})
DATA_ROOT_FIELDS = frozenset({
    "schema",
    "package_id",
    "case_id",
    "attempt_id",
    "nonce",
    "package_sha256",
    "source_host_id",
    "source_physical_host_id",
    "reproduction_host_id",
    "reproduction_physical_host_id",
    "source_data_root",
    "reproduction_data_root",
    "source_manifest_sha256",
    "reproduction_manifest_sha256",
    "source_identity_sha256",
    "reproduction_identity_sha256",
    "distinct_physical_hosts",
    "distinct_roots",
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
    "package_id",
    "case_id",
    "attempt_id",
    "nonce",
    "package_sha256",
    "source_host_id",
    "source_physical_host_id",
    "source_data_root",
    "source_manifest_sha256",
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
    "package_id",
    "case_id",
    "attempt_id",
    "nonce",
    "package_sha256",
    "host_id",
    "physical_host_id",
    "hostname",
    "reproduction_data_root",
    "reproduction_manifest_sha256",
    "reproduction_identity_sha256",
    "trusted_root_review_id",
    "artifact_chain_sha256",
    "attested",
    "receipt_present",
    "attestation_receipt_sha256",
    "cross_binding_sha256",
    "input_origin",
    "diagnostic_only",
})
JOIN_RECEIPT_FIELDS = frozenset({
    "schema",
    "join_id",
    "status",
    "package_id",
    "case_id",
    "attempt_id",
    "nonce",
    "package_sha256",
    "manifest_sha256",
    "receipt_sha256",
    "artifact_chain_sha256",
    "source_identity_sha256",
    "reproduction_identity_sha256",
    "trusted_root_review_id",
    "external_host_attestation_id",
    "package_binding_verified",
    "terminal_receipt_present",
    "terminal_receipt_sha256",
    "diagnostic_only",
    "full_product_reproduction",
    "independent_reproduction",
    "checkpoint",
    "credit",
    "cross_binding_sha256",
    "input_origin",
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
    "production_payload_opened": False,
    "large_asset_read": False,
    "host_probe_performed": False,
    "trusted_root_authenticated": False,
    "external_host_attested": False,
    "terminal_receipt_read": False,
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
STRUCTURAL_BLOCKED_STATUS = (
    "blocked_missing_trusted_root_external_host_and_full_product_terminal_join"
)
INVALID_BLOCKED_STATUS = "blocked_invalid_or_untrusted_join_projection"
CHECK_FIELDS = frozenset({
    "package_run_identity",
    "reader_prediction_scoring_chain",
    "distinct_data_root_identity",
    "trusted_root_cross_binding",
    "external_host_cross_binding",
    "full_product_receipt_cross_binding",
    "cross_binding_identity",
    "trusted_root_authenticated",
    "external_host_attested",
    "full_product_terminal_receipt",
})
BINDING_FIELDS = frozenset({
    "package_id",
    "case_id",
    "attempt_id",
    "nonce",
    "package_sha256",
    "manifest_sha256",
    "receipt_sha256",
    "artifact_chain_sha256",
    "source_host_id",
    "source_physical_host_id",
    "source_data_root",
    "source_manifest_sha256",
    "source_identity_sha256",
    "reproduction_host_id",
    "reproduction_physical_host_id",
    "reproduction_data_root",
    "reproduction_manifest_sha256",
    "reproduction_identity_sha256",
    "trusted_root_review_id",
    "root_id",
    "external_host_attestation_id",
    "join_id",
    "cross_binding_sha256",
    "trusted_root_authenticated",
    "external_host_attested",
    "full_product_terminal_receipt_present",
})


class ContractError(ValueError):
    """A bounded, fail-closed A8 join violation."""

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


def _text(value: Any, *, label: str) -> str:
    _require(type(value) is str and bool(value), "TEXT_MISSING",
             f"{label} must be a non-empty normalized string")
    _require(value == value.strip(), "TEXT_NOT_NORMALIZED",
             f"{label} contains leading or trailing whitespace")
    return value


def _sha(value: Any, *, label: str) -> str:
    _require(type(value) is str and SHA256_RE.fullmatch(value) is not None,
             "SHA256_INVALID", f"{label} is not a lowercase SHA-256 digest")
    return value


def _root(value: Any, *, label: str) -> str:
    raw = _text(value, label=label)
    _require(raw.startswith("/") and "\\" not in raw,
             "DATA_ROOT_INVALID", f"{label} must be an absolute POSIX root")
    _require(".." not in raw.split("/"), "DATA_ROOT_INVALID",
             f"{label} contains '..'")
    normalized = posixpath.normpath(raw)
    _require(normalized == raw and normalized not in ("", "/", "."),
             "DATA_ROOT_NOT_CANONICAL", f"{label} is not a canonical non-root path")
    return normalized


def _diagnostic_markers(value: Mapping[str, Any], *, label: str) -> None:
    _require(value.get("input_origin") == INPUT_ORIGIN, "INPUT_ORIGIN_INVALID",
             f"{label} is not a synthetic fixture")
    _require(value.get("diagnostic_only") is True, "DIAGNOSTIC_MARKER_MISSING",
             f"{label} is not diagnostic-only")


def _authority_markers(value: Mapping[str, Any], *, label: str) -> None:
    _diagnostic_markers(value, label=label)
    _require(value.get("full_product_reproduction") is False,
             "FULL_PRODUCT_CLAIM_FORBIDDEN", f"{label} claims full-product reproduction")
    _require(value.get("independent_reproduction") is False,
             "INDEPENDENT_REPRODUCTION_CLAIM_FORBIDDEN",
             f"{label} claims independent reproduction")
    _require(type(value.get("checkpoint")) is int and value.get("checkpoint") == 0,
             "CHECKPOINT_CLAIM_FORBIDDEN", f"{label}.checkpoint must be zero")
    _require(type(value.get("credit")) is int and value.get("credit") == 0,
             "CREDIT_CLAIM_FORBIDDEN", f"{label}.credit must be zero")


def _identity_hash(host_id: str, physical_host_id: str, data_root: str,
                   manifest_sha256: str, package_sha256: str) -> str:
    return sha256_json({
        "host_id": host_id,
        "physical_host_id": physical_host_id,
        "data_root": data_root,
        "manifest_sha256": manifest_sha256,
        "package_sha256": package_sha256,
    }, label="data-root identity")


def _artifact_chain_hash(artifacts: Mapping[str, str]) -> str:
    return sha256_json({role: artifacts[role] for role in ROLES},
                       label="reader/prediction/scoring artifact chain")


def _cross_binding_hash(context: Mapping[str, str]) -> str:
    return sha256_json({
        "package_id": context["package_id"],
        "case_id": context["case_id"],
        "attempt_id": context["attempt_id"],
        "nonce": context["nonce"],
        "package_sha256": context["package_sha256"],
        "manifest_sha256": context["manifest_sha256"],
        "receipt_sha256": context["receipt_sha256"],
        "artifact_chain_sha256": context["artifact_chain_sha256"],
        "source_host_id": context["source_host_id"],
        "source_physical_host_id": context["source_physical_host_id"],
        "source_data_root": context["source_data_root"],
        "source_manifest_sha256": context["source_manifest_sha256"],
        "source_identity_sha256": context["source_identity_sha256"],
        "reproduction_host_id": context["reproduction_host_id"],
        "reproduction_physical_host_id": context["reproduction_physical_host_id"],
        "reproduction_data_root": context["reproduction_data_root"],
        "reproduction_manifest_sha256": context["reproduction_manifest_sha256"],
        "reproduction_identity_sha256": context["reproduction_identity_sha256"],
        "trusted_root_review_id": context["trusted_root_review_id"],
        "root_id": context["root_id"],
        "external_host_attestation_id": context["external_host_attestation_id"],
        "join_id": context["join_id"],
    }, label="A8 full-product external-host/root cross-binding")


def _validate_identity(value: Any, *, label: str) -> dict[str, str]:
    row = _exact(value, IDENTITY_FIELDS, label=label)
    return {
        "host_id": _text(row["host_id"], label=f"{label}.host_id"),
        "physical_host_id": _text(row["physical_host_id"], label=f"{label}.physical_host_id"),
        "data_root": _root(row["data_root"], label=f"{label}.data_root"),
        "identity_sha256": _sha(row["identity_sha256"], label=f"{label}.identity_sha256"),
    }


def _run_identity(row: Mapping[str, Any], *, package: Mapping[str, Any], label: str) -> None:
    for field in ("package_id", "case_id", "attempt_id", "nonce", "package_sha256"):
        _require(row[field] == package[field], "PACKAGE_RUN_ID_MISMATCH",
                 f"{label}.{field} differs from package boundary")


def _validate_package(value: Any) -> dict[str, Any]:
    row = _exact(value, PACKAGE_FIELDS, label="package boundary")
    _require(row["schema"] == PACKAGE_SCHEMA, "PACKAGE_SCHEMA_MISMATCH",
             "package boundary schema is unsupported")
    _require(row["status"] == "verified_diagnostic_only",
             "PACKAGE_STATUS_INVALID", "package boundary is not the diagnostic verifier result")
    _require(row["package_binding_verified"] is True,
             "PACKAGE_BINDING_MISSING", "package boundary is not structurally verified")
    _authority_markers(row, label="package boundary")
    package = {
        "package_id": _text(row["package_id"], label="package_id"),
        "case_id": _text(row["case_id"], label="case_id"),
        "attempt_id": _text(row["attempt_id"], label="attempt_id"),
        "nonce": _text(row["nonce"], label="nonce"),
        "package_sha256": _sha(row["package_sha256"], label="package_sha256"),
        "manifest_sha256": _sha(row["manifest_sha256"], label="manifest_sha256"),
        "receipt_sha256": _sha(row["receipt_sha256"], label="receipt_sha256"),
    }
    source = _validate_identity(row["source"], label="package source")
    reproduction = _validate_identity(row["reproduction"], label="package reproduction")
    artifacts_row = _exact(row["artifact_digests"], ARTIFACT_FIELDS,
                           label="package artifact_digests")
    artifacts = {
        role: _sha(artifacts_row[role], label=f"package artifact_digests.{role}")
        for role in ROLES
    }
    chain_row = _exact(row["chain"], CHAIN_FIELDS, label="package chain")
    chain = {key: _sha(chain_row[key], label=f"package chain.{key}")
             for key in CHAIN_FIELDS}
    _require(chain["reader_artifact_sha256"] == artifacts["reader"],
             "ARTIFACT_CHAIN_MISMATCH", "package chain does not bind reader digest")
    _require(chain["prediction_reader_input_sha256"] == artifacts["reader"],
             "ARTIFACT_CHAIN_MISMATCH", "prediction does not bind reader digest")
    _require(chain["prediction_artifact_sha256"] == artifacts["prediction"],
             "ARTIFACT_CHAIN_MISMATCH", "package chain does not bind prediction digest")
    _require(chain["scoring_reader_input_sha256"] == artifacts["reader"],
             "ARTIFACT_CHAIN_MISMATCH", "scoring does not bind reader digest")
    _require(chain["scoring_prediction_input_sha256"] == artifacts["prediction"],
             "ARTIFACT_CHAIN_MISMATCH", "scoring does not bind prediction digest")
    _require(chain["scoring_artifact_sha256"] == artifacts["scoring"],
             "ARTIFACT_CHAIN_MISMATCH", "package chain does not bind scoring digest")
    artifact_chain = _sha(row["artifact_chain_sha256"], label="artifact_chain_sha256")
    _require(artifact_chain == _artifact_chain_hash(artifacts),
             "ARTIFACT_CHAIN_IDENTITY_MISMATCH",
             "package artifact-chain identity does not match role digests")
    _require(source["host_id"] != reproduction["host_id"],
             "PACKAGE_HOSTS_NOT_DISTINCT", "package source/reproduction hosts are identical")
    _require(source["physical_host_id"] != reproduction["physical_host_id"],
             "PACKAGE_PHYSICAL_HOSTS_NOT_DISTINCT",
             "package source/reproduction physical hosts are identical")
    _require(source["data_root"] != reproduction["data_root"],
             "PACKAGE_DATA_ROOTS_NOT_DISTINCT",
             "package source/reproduction data roots are identical")
    package.update({
        "source": source,
        "reproduction": reproduction,
        "artifacts": artifacts,
        "chain": chain,
        "artifact_chain_sha256": artifact_chain,
        "cross_binding_sha256": _sha(row["cross_binding_sha256"],
                                      label="package cross_binding_sha256"),
    })
    return package


def _validate_data_roots(value: Any, *, package: Mapping[str, Any]) -> dict[str, Any]:
    row = _exact(value, DATA_ROOT_FIELDS, label="distinct data-root identity")
    _require(row["schema"] == DATA_ROOT_SCHEMA, "DATA_ROOT_SCHEMA_MISMATCH",
             "data-root identity schema is unsupported")
    _diagnostic_markers(row, label="distinct data-root identity")
    _run_identity(row, package=package, label="data-root identity")
    source = package["source"]
    reproduction = package["reproduction"]
    source_host = _text(row["source_host_id"], label="source_host_id")
    source_physical = _text(row["source_physical_host_id"], label="source_physical_host_id")
    reproduction_host = _text(row["reproduction_host_id"], label="reproduction_host_id")
    reproduction_physical = _text(
        row["reproduction_physical_host_id"], label="reproduction_physical_host_id"
    )
    source_root = _root(row["source_data_root"], label="source_data_root")
    reproduction_root = _root(row["reproduction_data_root"], label="reproduction_data_root")
    source_manifest = _sha(row["source_manifest_sha256"], label="source_manifest_sha256")
    reproduction_manifest = _sha(
        row["reproduction_manifest_sha256"], label="reproduction_manifest_sha256"
    )
    _require(source_host == source["host_id"] and source_physical == source["physical_host_id"]
             and source_root == source["data_root"],
             "DATA_ROOT_SOURCE_MISMATCH", "source root identity is not bound to package source")
    _require(reproduction_host == reproduction["host_id"]
             and reproduction_physical == reproduction["physical_host_id"]
             and reproduction_root == reproduction["data_root"],
             "DATA_ROOT_REPRODUCTION_MISMATCH",
             "reproduction root identity is not bound to package reproduction")
    _require(source_host != reproduction_host, "HOSTS_NOT_DISTINCT",
             "source and reproduction hosts are identical")
    _require(source_physical != reproduction_physical, "PHYSICAL_HOSTS_NOT_DISTINCT",
             "source and reproduction physical hosts are identical")
    _require(source_root != reproduction_root, "DATA_ROOTS_NOT_DISTINCT",
             "source and reproduction data roots are identical")
    _require(source_manifest != reproduction_manifest, "MANIFESTS_NOT_DISTINCT",
             "source and reproduction manifest identities are identical")
    package_sha = package["package_sha256"]
    expected_source_identity = _identity_hash(
        source_host, source_physical, source_root, source_manifest, package_sha
    )
    expected_reproduction_identity = _identity_hash(
        reproduction_host, reproduction_physical, reproduction_root,
        reproduction_manifest, package_sha
    )
    _require(row["source_identity_sha256"] == expected_source_identity
             and row["source_identity_sha256"] == source["identity_sha256"],
             "DATA_ROOT_SOURCE_IDENTITY_MISMATCH",
             "source identity does not bind host, physical host, root, manifest and package")
    _require(row["reproduction_identity_sha256"] == expected_reproduction_identity
             and row["reproduction_identity_sha256"] == reproduction["identity_sha256"],
             "DATA_ROOT_REPRODUCTION_IDENTITY_MISMATCH",
             "reproduction identity does not bind host, physical host, root, manifest and package")
    _require(row["distinct_physical_hosts"] is True,
             "DISTINCT_PHYSICAL_HOSTS_NOT_ASSERTED",
             "distinct physical hosts are not asserted")
    _require(row["distinct_roots"] is True, "DISTINCT_ROOTS_NOT_ASSERTED",
             "distinct data roots are not asserted")
    _require(row["manifest_binding_verified"] is True,
             "MANIFEST_BINDING_NOT_VERIFIED", "manifest binding is not verified")
    return {
        "source_host_id": source_host,
        "source_physical_host_id": source_physical,
        "source_data_root": source_root,
        "source_manifest_sha256": source_manifest,
        "source_identity_sha256": expected_source_identity,
        "reproduction_host_id": reproduction_host,
        "reproduction_physical_host_id": reproduction_physical,
        "reproduction_data_root": reproduction_root,
        "reproduction_manifest_sha256": reproduction_manifest,
        "reproduction_identity_sha256": expected_reproduction_identity,
        "cross_binding_sha256": _sha(row["cross_binding_sha256"],
                                      label="data-root cross_binding_sha256"),
    }


def _validate_trusted_root(value: Any, *, package: Mapping[str, Any],
                           roots: Mapping[str, Any]) -> dict[str, Any]:
    row = _exact(value, TRUSTED_ROOT_FIELDS, label="trusted-root review")
    _require(row["schema"] == TRUSTED_ROOT_SCHEMA, "TRUSTED_ROOT_SCHEMA_MISMATCH",
             "trusted-root review schema is unsupported")
    _diagnostic_markers(row, label="trusted-root review")
    _run_identity(row, package=package, label="trusted-root review")
    review_id = _text(row["review_id"], label="trusted-root review_id")
    root_id = _text(row["root_id"], label="trusted-root root_id")
    _text(row["authority_scope"], label="trusted-root authority_scope")
    _require(row["source_host_id"] == roots["source_host_id"]
             and row["source_physical_host_id"] == roots["source_physical_host_id"],
             "TRUSTED_ROOT_HOST_MISMATCH", "trusted-root review is not bound to source host")
    _require(_root(row["source_data_root"], label="trusted-root source_data_root")
             == roots["source_data_root"], "TRUSTED_ROOT_ROOT_MISMATCH",
             "trusted-root review is not bound to source data root")
    _require(row["source_manifest_sha256"] == roots["source_manifest_sha256"],
             "TRUSTED_ROOT_MANIFEST_MISMATCH",
             "trusted-root review is not bound to source manifest")
    _require(row["source_identity_sha256"] == roots["source_identity_sha256"],
             "TRUSTED_ROOT_IDENTITY_MISMATCH",
             "trusted-root review is not bound to source identity")
    _require(row["decision"] == "not_attested" and row["authenticated"] is False
             and row["receipt_present"] is False and row["review_receipt_sha256"] is None,
             "TRUSTED_ROOT_CLAIM_FORBIDDEN",
             "synthetic input cannot claim a trusted-root attestation")
    return {
        "review_id": review_id,
        "root_id": root_id,
        "cross_binding_sha256": _sha(row["cross_binding_sha256"],
                                      label="trusted-root cross_binding_sha256"),
    }


def _validate_external_host(value: Any, *, package: Mapping[str, Any],
                            roots: Mapping[str, Any], trusted_root: Mapping[str, Any]) -> dict[str, Any]:
    row = _exact(value, EXTERNAL_HOST_FIELDS, label="external-host attestation")
    _require(row["schema"] == EXTERNAL_HOST_SCHEMA, "EXTERNAL_HOST_SCHEMA_MISMATCH",
             "external-host attestation schema is unsupported")
    _diagnostic_markers(row, label="external-host attestation")
    _run_identity(row, package=package, label="external-host attestation")
    attestation_id = _text(row["attestation_id"], label="external-host attestation_id")
    _require(row["role"] == "reproduction_host", "EXTERNAL_HOST_ROLE_MISMATCH",
             "external-host attestation role must be reproduction_host")
    _require(row["host_id"] == roots["reproduction_host_id"]
             and row["physical_host_id"] == roots["reproduction_physical_host_id"],
             "EXTERNAL_HOST_IDENTITY_MISMATCH",
             "external-host attestation is not bound to reproduction host identity")
    _text(row["hostname"], label="external-host hostname")
    _require(_root(row["reproduction_data_root"], label="external-host reproduction_data_root")
             == roots["reproduction_data_root"], "EXTERNAL_HOST_ROOT_MISMATCH",
             "external-host attestation is not bound to reproduction data root")
    _require(row["reproduction_manifest_sha256"] == roots["reproduction_manifest_sha256"],
             "EXTERNAL_HOST_MANIFEST_MISMATCH",
             "external-host attestation is not bound to reproduction manifest")
    _require(row["reproduction_identity_sha256"] == roots["reproduction_identity_sha256"],
             "EXTERNAL_HOST_IDENTITY_MISMATCH",
             "external-host attestation is not bound to reproduction identity")
    _require(row["trusted_root_review_id"] == trusted_root["review_id"],
             "EXTERNAL_HOST_ROOT_REVIEW_MISMATCH",
             "external-host attestation is not bound to trusted-root review")
    _require(row["artifact_chain_sha256"] == package["artifact_chain_sha256"],
             "EXTERNAL_HOST_ARTIFACT_CHAIN_MISMATCH",
             "external-host attestation is not bound to reader/prediction/scoring chain")
    _require(row["attested"] is False and row["receipt_present"] is False
             and row["attestation_receipt_sha256"] is None,
             "EXTERNAL_HOST_CLAIM_FORBIDDEN",
             "synthetic input cannot claim an external-host attestation")
    return {
        "attestation_id": attestation_id,
        "cross_binding_sha256": _sha(row["cross_binding_sha256"],
                                      label="external-host cross_binding_sha256"),
    }


def _validate_join(value: Any, *, package: Mapping[str, Any], roots: Mapping[str, Any],
                   trusted_root: Mapping[str, Any], external_host: Mapping[str, Any]) -> dict[str, Any]:
    row = _exact(value, JOIN_RECEIPT_FIELDS, label="full-product join receipt")
    _require(row["schema"] == JOIN_SCHEMA, "JOIN_SCHEMA_MISMATCH",
             "full-product join receipt schema is unsupported")
    _authority_markers(row, label="full-product join receipt")
    _run_identity(row, package=package, label="full-product join receipt")
    join_id = _text(row["join_id"], label="full-product join_id")
    _require(row["status"] == "verified_diagnostic_only", "JOIN_STATUS_INVALID",
             "join receipt must remain diagnostic-only")
    _require(row["manifest_sha256"] == package["manifest_sha256"]
             and row["receipt_sha256"] == package["receipt_sha256"],
             "JOIN_PACKAGE_RECEIPT_MISMATCH",
             "join receipt is not bound to package manifest/receipt digests")
    _require(row["artifact_chain_sha256"] == package["artifact_chain_sha256"],
             "JOIN_ARTIFACT_CHAIN_MISMATCH",
             "join receipt is not bound to reader/prediction/scoring chain")
    _require(row["source_identity_sha256"] == roots["source_identity_sha256"]
             and row["reproduction_identity_sha256"] == roots["reproduction_identity_sha256"],
             "JOIN_DATA_ROOT_IDENTITY_MISMATCH",
             "join receipt is not bound to both data-root identities")
    _require(row["trusted_root_review_id"] == trusted_root["review_id"],
             "JOIN_TRUSTED_ROOT_MISMATCH",
             "join receipt is not bound to trusted-root review")
    _require(row["external_host_attestation_id"] == external_host["attestation_id"],
             "JOIN_EXTERNAL_HOST_MISMATCH",
             "join receipt is not bound to external-host attestation")
    _require(row["package_binding_verified"] is True,
             "JOIN_PACKAGE_BINDING_MISSING", "join receipt lacks package binding")
    _require(row["terminal_receipt_present"] is False
             and row["terminal_receipt_sha256"] is None,
             "FULL_PRODUCT_CLAIM_FORBIDDEN",
             "synthetic input cannot carry a terminal full-product receipt")
    return {
        "join_id": join_id,
        "cross_binding_sha256": _sha(row["cross_binding_sha256"],
                                      label="join cross_binding_sha256"),
    }


def _base_report() -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "version": "a8-full-product-external-host-root-join-gap-v1",
        "report_id": "a8-full-product-external-host-root-join-gap-2026-09-29",
        "scope": (
            "Bounded join of the A8 full-product reader/prediction/scoring chain "
            "with distinct data roots, trusted-root and external-host placeholders."
        ),
        "status": INVALID_BLOCKED_STATUS,
        "passed": False,
        "structural_contract_passed": False,
        "input_origin": INPUT_ORIGIN,
        "diagnostic_only": True,
        **FALSE_CLAIMS,
        "mutations": dict(ZERO_MUTATIONS),
        "execution_constraints": dict(EXECUTION_CONSTRAINTS),
        "checks": {key: False for key in CHECK_FIELDS},
        "bindings": None,
        "blockers": [],
        "errors": [],
        "interpretation": (
            "A structurally valid synthetic join is identity evidence only. It does "
            "not authenticate a trusted root, attest an external host, prove "
            "independent reproduction, or issue Core credit."
        ),
    }


def _binding_context(package: Mapping[str, Any], roots: Mapping[str, Any],
                     trusted_root: Mapping[str, Any], external_host: Mapping[str, Any],
                     join: Mapping[str, Any]) -> dict[str, str]:
    return {
        "package_id": package["package_id"],
        "case_id": package["case_id"],
        "attempt_id": package["attempt_id"],
        "nonce": package["nonce"],
        "package_sha256": package["package_sha256"],
        "manifest_sha256": package["manifest_sha256"],
        "receipt_sha256": package["receipt_sha256"],
        "artifact_chain_sha256": package["artifact_chain_sha256"],
        "source_host_id": roots["source_host_id"],
        "source_physical_host_id": roots["source_physical_host_id"],
        "source_data_root": roots["source_data_root"],
        "source_manifest_sha256": roots["source_manifest_sha256"],
        "source_identity_sha256": roots["source_identity_sha256"],
        "reproduction_host_id": roots["reproduction_host_id"],
        "reproduction_physical_host_id": roots["reproduction_physical_host_id"],
        "reproduction_data_root": roots["reproduction_data_root"],
        "reproduction_manifest_sha256": roots["reproduction_manifest_sha256"],
        "reproduction_identity_sha256": roots["reproduction_identity_sha256"],
        "trusted_root_review_id": trusted_root["review_id"],
        "root_id": trusted_root["root_id"],
        "external_host_attestation_id": external_host["attestation_id"],
        "join_id": join["join_id"],
    }


def build_report(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one bounded synthetic join projection."""
    report = _base_report()
    try:
        root = _exact(projection, INPUT_FIELDS, label="A8 full-product join projection")
        _require(root["schema"] == SCHEMA, "INPUT_SCHEMA_MISMATCH",
                 "join projection schema is unsupported")
        _require(root["input_origin"] == INPUT_ORIGIN, "INPUT_ORIGIN_INVALID",
                 "join projection is not synthetic_fixture")
        _require(root["diagnostic_only"] is True, "DIAGNOSTIC_MARKER_MISSING",
                 "join projection is not diagnostic-only")
        package = _validate_package(root["package_boundary"])
        roots = _validate_data_roots(root["data_root_identity"], package=package)
        trusted_root = _validate_trusted_root(
            root["trusted_root_review"], package=package, roots=roots
        )
        external_host = _validate_external_host(
            root["external_host_attestation"], package=package, roots=roots,
            trusted_root=trusted_root
        )
        join = _validate_join(
            root["full_product_join_receipt"], package=package, roots=roots,
            trusted_root=trusted_root, external_host=external_host
        )
        context = _binding_context(package, roots, trusted_root, external_host, join)
        expected_binding = _cross_binding_hash(context)
        for section, item in (
            ("package boundary", package),
            ("data-root identity", roots),
            ("trusted-root review", trusted_root),
            ("external-host attestation", external_host),
            ("full-product join receipt", join),
        ):
            _require(item["cross_binding_sha256"] == expected_binding,
                     "CROSS_BINDING_HASH_MISMATCH",
                     f"{section} does not share the canonical join identity")
        report.update({
            "status": STRUCTURAL_BLOCKED_STATUS,
            "passed": True,
            "structural_contract_passed": True,
            "checks": {
                "package_run_identity": True,
                "reader_prediction_scoring_chain": True,
                "distinct_data_root_identity": True,
                "trusted_root_cross_binding": True,
                "external_host_cross_binding": True,
                "full_product_receipt_cross_binding": True,
                "cross_binding_identity": True,
                "trusted_root_authenticated": False,
                "external_host_attested": False,
                "full_product_terminal_receipt": False,
            },
            "bindings": {
                **context,
                "cross_binding_sha256": expected_binding,
                "trusted_root_authenticated": False,
                "external_host_attested": False,
                "full_product_terminal_receipt_present": False,
            },
            "blockers": [
                "trusted_root_review_receipt_not_present",
                "external_host_attestation_receipt_not_present",
                "full_product_terminal_receipt_not_present",
                "synthetic_cross_binding_is_identity_only_not_evidence",
            ],
            "next_required": [
                "obtain a real independently trusted root review receipt bound to source identity",
                "obtain a real external-host attestation bound to reproduction identity and artifact chain",
                "obtain a real terminal full-product receipt bound to the same package join",
                "re-run the Core independent_reproduction gate verifier",
            ],
        })
    except ContractError as error:
        report["errors"] = [{"code": error.code, "message": str(error)}]
        report["blockers"] = ["invalid_or_untrusted_full_product_external_host_root_join"]
    return report


def _context_from_bindings(bindings: Mapping[str, Any]) -> dict[str, str]:
    return {key: str(bindings[key]) for key in (
        "package_id", "case_id", "attempt_id", "nonce", "package_sha256",
        "manifest_sha256", "receipt_sha256", "artifact_chain_sha256",
        "source_host_id", "source_physical_host_id", "source_data_root",
        "source_manifest_sha256", "source_identity_sha256", "reproduction_host_id",
        "reproduction_physical_host_id", "reproduction_data_root",
        "reproduction_manifest_sha256", "reproduction_identity_sha256",
        "trusted_root_review_id", "root_id", "external_host_attestation_id", "join_id",
    )}


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Return errors if a generated report carries authority or mutation."""
    errors: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("report.schema mismatch")
    if report.get("input_origin") != INPUT_ORIGIN:
        errors.append("report.input_origin must be synthetic_fixture")
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
    if not isinstance(checks, Mapping) or set(checks) != CHECK_FIELDS:
        errors.append("report.checks fields are not exact")
    status = report.get("status")
    if status == STRUCTURAL_BLOCKED_STATUS:
        if report.get("passed") is not True or report.get("structural_contract_passed") is not True:
            errors.append("structural report must be passed with structural_contract_passed")
        expected_checks = {
            "package_run_identity": True,
            "reader_prediction_scoring_chain": True,
            "distinct_data_root_identity": True,
            "trusted_root_cross_binding": True,
            "external_host_cross_binding": True,
            "full_product_receipt_cross_binding": True,
            "cross_binding_identity": True,
            "trusted_root_authenticated": False,
            "external_host_attested": False,
            "full_product_terminal_receipt": False,
        }
        if isinstance(checks, Mapping) and dict(checks) != expected_checks:
            errors.append("structural report.checks drift")
        bindings = report.get("bindings")
        if not isinstance(bindings, Mapping) or set(bindings) != BINDING_FIELDS:
            errors.append("structural report.bindings fields are not exact")
        else:
            for key in (
                "trusted_root_authenticated",
                "external_host_attested",
                "full_product_terminal_receipt_present",
            ):
                if bindings.get(key) is not False:
                    errors.append(f"report.bindings.{key} must remain false")
            try:
                for key in (
                    "package_id", "case_id", "attempt_id", "nonce", "source_host_id",
                    "source_physical_host_id", "source_data_root", "source_manifest_sha256",
                    "reproduction_host_id", "reproduction_physical_host_id",
                    "reproduction_data_root", "reproduction_manifest_sha256",
                    "trusted_root_review_id", "root_id", "external_host_attestation_id",
                    "join_id",
                ):
                    _text(bindings[key], label=f"report.bindings.{key}")
                for key in (
                    "package_sha256", "manifest_sha256", "receipt_sha256",
                    "artifact_chain_sha256", "source_identity_sha256",
                    "reproduction_identity_sha256",
                ):
                    _sha(bindings[key], label=f"report.bindings.{key}")
                _root(bindings["source_data_root"], label="report source_data_root")
                _root(bindings["reproduction_data_root"], label="report reproduction_data_root")
                _require(bindings["source_host_id"] != bindings["reproduction_host_id"],
                         "HOSTS_NOT_DISTINCT", "report source/reproduction hosts are identical")
                _require(
                    bindings["source_physical_host_id"] != bindings["reproduction_physical_host_id"],
                    "PHYSICAL_HOSTS_NOT_DISTINCT",
                    "report source/reproduction physical hosts are identical",
                )
                _require(bindings["source_data_root"] != bindings["reproduction_data_root"],
                         "DATA_ROOTS_NOT_DISTINCT",
                         "report source/reproduction data roots are identical")
                expected_binding = _cross_binding_hash(_context_from_bindings(bindings))
                if bindings.get("cross_binding_sha256") != expected_binding:
                    errors.append("report.bindings.cross_binding_sha256 mismatch")
            except ContractError as error:
                errors.append(f"report.bindings invalid: {error.code}")
    elif status == INVALID_BLOCKED_STATUS:
        if report.get("passed") is not False or report.get("structural_contract_passed") is not False:
            errors.append("invalid report must remain not passed")
        if not isinstance(report.get("errors"), list) or not report["errors"]:
            errors.append("invalid report.errors must be non-empty")
    else:
        errors.append("report.status is unsupported")
    return sorted(set(errors))


def synthetic_projection() -> dict[str, Any]:
    """Return a fully cross-bound but non-authorizing synthetic projection."""
    package_id = "a8-synthetic-full-product-join-001"
    case_id = "case-001"
    attempt_id = "attempt-001"
    nonce = "nonce-001"
    package_sha = "a" * 64
    manifest_sha = "b" * 64
    receipt_sha = "c" * 64
    source_manifest = "d" * 64
    reproduction_manifest = "e" * 64
    source = {
        "host_id": "source-host-001",
        "physical_host_id": "source-physical-001",
        "data_root": "/synthetic/a8-source-001",
    }
    reproduction = {
        "host_id": "external-reproduction-host-001",
        "physical_host_id": "external-reproduction-physical-001",
        "data_root": "/synthetic/a8-reproduction-001",
    }
    source["identity_sha256"] = _identity_hash(
        source["host_id"], source["physical_host_id"], source["data_root"],
        source_manifest, package_sha
    )
    reproduction["identity_sha256"] = _identity_hash(
        reproduction["host_id"], reproduction["physical_host_id"],
        reproduction["data_root"], reproduction_manifest, package_sha
    )
    artifacts = {"reader": "f" * 64, "prediction": "0" * 64, "scoring": "1" * 64}
    chain = {
        "reader_artifact_sha256": artifacts["reader"],
        "prediction_reader_input_sha256": artifacts["reader"],
        "prediction_artifact_sha256": artifacts["prediction"],
        "scoring_reader_input_sha256": artifacts["reader"],
        "scoring_prediction_input_sha256": artifacts["prediction"],
        "scoring_artifact_sha256": artifacts["scoring"],
    }
    artifact_chain = _artifact_chain_hash(artifacts)
    package = {
        "package_id": package_id,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
        "package_sha256": package_sha,
        "manifest_sha256": manifest_sha,
        "receipt_sha256": receipt_sha,
        "source": source,
        "reproduction": reproduction,
        "artifact_digests": artifacts,
        "chain": chain,
        "artifact_chain_sha256": artifact_chain,
    }
    trusted_review_id = "synthetic-trusted-root-review-missing-v1"
    root_id = "synthetic-root-not-authority-v1"
    external_attestation_id = "synthetic-external-host-attestation-missing-v1"
    join_id = "synthetic-full-product-external-host-root-join-missing-v1"
    context = {
        "package_id": package_id,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
        "package_sha256": package_sha,
        "manifest_sha256": manifest_sha,
        "receipt_sha256": receipt_sha,
        "artifact_chain_sha256": artifact_chain,
        "source_host_id": source["host_id"],
        "source_physical_host_id": source["physical_host_id"],
        "source_data_root": source["data_root"],
        "source_manifest_sha256": source_manifest,
        "source_identity_sha256": source["identity_sha256"],
        "reproduction_host_id": reproduction["host_id"],
        "reproduction_physical_host_id": reproduction["physical_host_id"],
        "reproduction_data_root": reproduction["data_root"],
        "reproduction_manifest_sha256": reproduction_manifest,
        "reproduction_identity_sha256": reproduction["identity_sha256"],
        "trusted_root_review_id": trusted_review_id,
        "root_id": root_id,
        "external_host_attestation_id": external_attestation_id,
        "join_id": join_id,
    }
    cross_binding = _cross_binding_hash(context)

    def authority(**extra: Any) -> dict[str, Any]:
        return {
            "input_origin": INPUT_ORIGIN,
            "diagnostic_only": True,
            "full_product_reproduction": False,
            "independent_reproduction": False,
            "checkpoint": 0,
            "credit": 0,
            **extra,
        }

    package_projection = {
        "schema": PACKAGE_SCHEMA,
        "status": "verified_diagnostic_only",
        "package_binding_verified": True,
        **package,
        "cross_binding_sha256": cross_binding,
        **authority(),
    }
    roots_projection = {
        "schema": DATA_ROOT_SCHEMA,
        "package_id": package_id,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
        "package_sha256": package_sha,
        "source_host_id": source["host_id"],
        "source_physical_host_id": source["physical_host_id"],
        "reproduction_host_id": reproduction["host_id"],
        "reproduction_physical_host_id": reproduction["physical_host_id"],
        "source_data_root": source["data_root"],
        "reproduction_data_root": reproduction["data_root"],
        "source_manifest_sha256": source_manifest,
        "reproduction_manifest_sha256": reproduction_manifest,
        "source_identity_sha256": source["identity_sha256"],
        "reproduction_identity_sha256": reproduction["identity_sha256"],
        "distinct_physical_hosts": True,
        "distinct_roots": True,
        "manifest_binding_verified": True,
        "cross_binding_sha256": cross_binding,
        **{key: authority()[key] for key in ("input_origin", "diagnostic_only")},
    }
    trusted_projection = {
        "schema": TRUSTED_ROOT_SCHEMA,
        "review_id": trusted_review_id,
        "root_id": root_id,
        "authority_scope": "core.independent_reproduction",
        "package_id": package_id,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
        "package_sha256": package_sha,
        "source_host_id": source["host_id"],
        "source_physical_host_id": source["physical_host_id"],
        "source_data_root": source["data_root"],
        "source_manifest_sha256": source_manifest,
        "source_identity_sha256": source["identity_sha256"],
        "decision": "not_attested",
        "authenticated": False,
        "receipt_present": False,
        "review_receipt_sha256": None,
        "cross_binding_sha256": cross_binding,
        **{key: authority()[key] for key in ("input_origin", "diagnostic_only")},
    }
    external_projection = {
        "schema": EXTERNAL_HOST_SCHEMA,
        "attestation_id": external_attestation_id,
        "role": "reproduction_host",
        "package_id": package_id,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
        "package_sha256": package_sha,
        "host_id": reproduction["host_id"],
        "physical_host_id": reproduction["physical_host_id"],
        "hostname": reproduction["host_id"],
        "reproduction_data_root": reproduction["data_root"],
        "reproduction_manifest_sha256": reproduction_manifest,
        "reproduction_identity_sha256": reproduction["identity_sha256"],
        "trusted_root_review_id": trusted_review_id,
        "artifact_chain_sha256": artifact_chain,
        "attested": False,
        "receipt_present": False,
        "attestation_receipt_sha256": None,
        "cross_binding_sha256": cross_binding,
        **{key: authority()[key] for key in ("input_origin", "diagnostic_only")},
    }
    join_projection = {
        "schema": JOIN_SCHEMA,
        "join_id": join_id,
        "status": "verified_diagnostic_only",
        "package_id": package_id,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
        "package_sha256": package_sha,
        "manifest_sha256": manifest_sha,
        "receipt_sha256": receipt_sha,
        "artifact_chain_sha256": artifact_chain,
        "source_identity_sha256": source["identity_sha256"],
        "reproduction_identity_sha256": reproduction["identity_sha256"],
        "trusted_root_review_id": trusted_review_id,
        "external_host_attestation_id": external_attestation_id,
        "package_binding_verified": True,
        "terminal_receipt_present": False,
        "terminal_receipt_sha256": None,
        "diagnostic_only": True,
        "full_product_reproduction": False,
        "independent_reproduction": False,
        "checkpoint": 0,
        "credit": 0,
        "cross_binding_sha256": cross_binding,
        "input_origin": INPUT_ORIGIN,
    }
    return {
        "schema": SCHEMA,
        "input_origin": INPUT_ORIGIN,
        "diagnostic_only": True,
        "package_boundary": package_projection,
        "data_root_identity": roots_projection,
        "trusted_root_review": trusted_projection,
        "external_host_attestation": external_projection,
        "full_product_join_receipt": join_projection,
    }


def _read_projection(path: Path) -> Mapping[str, Any]:
    try:
        value, _, _ = read_bounded_json_object(
            path, label="A8 full-product join projection", max_bytes=MAX_INPUT_BYTES
        )
    except SecureReadError as error:
        code = "INPUT_SIZE_OUT_OF_BOUNDS" if error.code == "INPUT_TOO_LARGE" else error.code
        raise ContractError(code, str(error)) from error
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
    audit.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "audit":
        try:
            projection = synthetic_projection() if args.synthetic else _read_projection(args.input)
            report = build_report(projection)
        except (OSError, ContractError) as error:
            report = _base_report()
            report["errors"] = [{"code": getattr(error, "code", "INPUT_ERROR"),
                                 "message": str(error)}]
            report["blockers"] = ["invalid_or_untrusted_full_product_external_host_root_join"]
        write_json(args.output, report)
        return 0
    try:
        report, _, _ = read_bounded_json_object(
            args.report, label="A8 full-product join report", max_bytes=MAX_INPUT_BYTES
        )
    except SecureReadError as error:
        print(str(error))
        return 1
    errors = validate_report(report)
    if errors:
        for error in errors:
            print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
