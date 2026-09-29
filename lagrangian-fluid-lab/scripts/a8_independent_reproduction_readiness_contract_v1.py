#!/usr/bin/env python3
"""Validate the smallest A8 independent-reproduction readiness boundary.

This contract is intentionally narrower than the existing typed-evidence
preflight.  It consumes one bounded, canonical in-memory projection and binds
three separate concerns without treating any of them as production authority:

* the existing typed-preflight projection;
* a synthetic trusted-root review placeholder;
* a synthetic external-host-attestation placeholder; and
* source/reproduction data-root identities bound to their manifest/package
  hashes.

The current fixture deliberately has no trusted root review and no external
host receipt.  Therefore a structurally valid input produces a blocked,
fail-closed readiness report.  This module never authenticates a root,
manufactures an external receipt, opens production artifacts, starts a native
solver/worker/GPU/queue, or mutates Core campaign state.  It is a diagnostic
contract only: ``independent_reproduction`` is always false and credit is
always zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.core_independent_reproduction_secure_io_v1 import (
    SecureReadError,
    read_bounded_json_object,
)


SCHEMA = "core.reproduction.a8_independent_readiness_input.v1"
REPORT_SCHEMA = "core.reproduction.a8_independent_readiness_report.v1"
TRUSTED_ROOT_SCHEMA = "core.reproduction.trusted_root_review.v1"
EXTERNAL_HOST_SCHEMA = "core.reproduction.external_host_attestation.v1"
DATA_ROOT_SCHEMA = "core.reproduction.data_root_identity.v1"
PREFLIGHT_SCHEMA = "core.reproduction.independent_preflight.v1"
STRUCTURAL_BLOCKED_STATUS = "blocked_missing_trusted_root_and_external_host_attestation"
INVALID_BLOCKED_STATUS = "blocked"
INPUT_ORIGIN = "synthetic_fixture"
MAX_INPUT_BYTES = 128 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)

INPUT_FIELDS = frozenset({
    "schema",
    "input_origin",
    "preflight",
    "trusted_root_review",
    "external_host_attestation",
    "data_root_identity",
})
PREFLIGHT_FIELDS = frozenset({
    "schema",
    "status",
    "structural_preflight_passed",
    "typed_chain_complete",
    "distinct_physical_hosts",
    "distinct_data_roots",
    "source_host_id",
    "reproduction_host_id",
    "source_data_root",
    "reproduction_data_root",
    "package_sha256",
    "diagnostic_only",
    "independent_reproduction",
    "full_product_reproduction",
    "credit",
    "qualification_credit",
    "input_origin",
})
TRUSTED_ROOT_FIELDS = frozenset({
    "schema",
    "review_id",
    "root_id",
    "decision",
    "authenticated",
    "authority_scope",
    "review_ref",
    "input_origin",
    "diagnostic_only",
})
EXTERNAL_HOST_FIELDS = frozenset({
    "schema",
    "role",
    "host_id",
    "hostname",
    "attested",
    "receipt_present",
    "attestation_ref",
    "input_origin",
    "diagnostic_only",
})
DATA_ROOT_FIELDS = frozenset({
    "schema",
    "source_data_root",
    "reproduction_data_root",
    "distinct_roots",
    "package_sha256",
    "source_manifest_sha256",
    "reproduction_manifest_sha256",
    "source_identity_sha256",
    "reproduction_identity_sha256",
    "manifest_binding_verified",
    "input_origin",
    "diagnostic_only",
})

FALSE_CLAIMS = {
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
    "production_artifacts_read": False,
    "external_host_receipt_opened": False,
    "trusted_root_authenticated": False,
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
BINDING_FIELDS = frozenset({
    "source_host_id",
    "reproduction_host_id",
    "source_data_root",
    "reproduction_data_root",
    "package_sha256",
    "source_manifest_sha256",
    "reproduction_manifest_sha256",
    "source_identity_sha256",
    "reproduction_identity_sha256",
    "trusted_root_authenticated",
    "external_host_attested",
})


class ContractError(ValueError):
    """A bounded readiness-contract violation."""

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


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any, *, label: str = "value") -> str:
    return sha256_bytes(canonical_json_bytes(value, label=label))


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


def _identity_hash(data_root: str, manifest_sha256: str, package_sha256: str) -> str:
    return sha256_json({
        "data_root": data_root,
        "manifest_sha256": manifest_sha256,
        "package_sha256": package_sha256,
    }, label="data-root identity")


def _validate_preflight(value: Any) -> dict[str, Any]:
    row = _exact(value, PREFLIGHT_FIELDS, label="preflight projection")
    _require(row["schema"] == PREFLIGHT_SCHEMA,
             "PREFLIGHT_SCHEMA_MISMATCH", "preflight schema is unsupported")
    _require(row["status"] == "pass"
             and row["structural_preflight_passed"] is True
             and row["typed_chain_complete"] is True,
             "PREFLIGHT_NOT_STRUCTURALLY_PASSED",
             "typed preflight projection is not structurally complete")
    _require(row["distinct_physical_hosts"] is True
             and row["distinct_data_roots"] is True,
             "PREFLIGHT_DISTINCTNESS_MISSING",
             "typed preflight does not assert distinct hosts and roots")
    _diagnostic_markers(row, label="preflight projection")
    _require(row["independent_reproduction"] is False
             and row["full_product_reproduction"] is False
             and row["credit"] == 0
             and row["qualification_credit"] == 0,
             "PREFLIGHT_AUTHORITY_CLAIM",
             "preflight projection attempts to claim independent or credited evidence")
    source_host = _text(row["source_host_id"], label="preflight source_host_id")
    reproduction_host = _text(row["reproduction_host_id"],
                               label="preflight reproduction_host_id")
    _require(source_host != reproduction_host, "HOST_IDENTITY_NOT_DISTINCT",
             "preflight source and reproduction host ids are identical")
    source_root = _root(row["source_data_root"], label="preflight source_data_root")
    reproduction_root = _root(row["reproduction_data_root"],
                              label="preflight reproduction_data_root")
    _require(source_root != reproduction_root, "DATA_ROOTS_NOT_DISTINCT",
             "preflight source and reproduction roots are identical")
    return {
        "source_host_id": source_host,
        "reproduction_host_id": reproduction_host,
        "source_data_root": source_root,
        "reproduction_data_root": reproduction_root,
        "package_sha256": _sha(row["package_sha256"], label="preflight package_sha256"),
    }


def _validate_root_review(value: Any) -> dict[str, Any]:
    row = _exact(value, TRUSTED_ROOT_FIELDS, label="trusted-root review")
    _require(row["schema"] == TRUSTED_ROOT_SCHEMA,
             "TRUSTED_ROOT_SCHEMA_MISMATCH", "trusted-root review schema is unsupported")
    _diagnostic_markers(row, label="trusted-root review")
    _text(row["review_id"], label="trusted-root review_id")
    _text(row["root_id"], label="trusted-root root_id")
    _text(row["authority_scope"], label="trusted-root authority_scope")
    _require(row["decision"] == "not_attested",
             "TRUSTED_ROOT_DECISION_UNEXPECTED",
             "synthetic trusted-root fixture must remain not_attested")
    _require(row["authenticated"] is False and row["review_ref"] is None,
             "TRUSTED_ROOT_CLAIM_FORBIDDEN",
             "synthetic input cannot authenticate or carry a trusted-root receipt")
    return {
        "review_id": row["review_id"],
        "root_id": row["root_id"],
        "authenticated": False,
        "receipt_present": False,
    }


def _validate_external_host(value: Any, *, expected_host_id: str) -> dict[str, Any]:
    row = _exact(value, EXTERNAL_HOST_FIELDS, label="external-host attestation")
    _require(row["schema"] == EXTERNAL_HOST_SCHEMA,
             "EXTERNAL_HOST_SCHEMA_MISMATCH",
             "external-host attestation schema is unsupported")
    _diagnostic_markers(row, label="external-host attestation")
    _require(row["role"] == "reproduction_host", "EXTERNAL_HOST_ROLE_MISMATCH",
             "external-host attestation must describe reproduction_host")
    _require(_text(row["host_id"], label="external-host host_id") == expected_host_id,
             "EXTERNAL_HOST_ID_MISMATCH",
             "external-host attestation is not bound to the preflight host")
    _text(row["hostname"], label="external-host hostname")
    _require(row["attested"] is False and row["receipt_present"] is False
             and row["attestation_ref"] is None,
             "EXTERNAL_HOST_CLAIM_FORBIDDEN",
             "synthetic input cannot claim or carry an external host receipt")
    return {
        "host_id": expected_host_id,
        "attested": False,
        "receipt_present": False,
    }


def _validate_data_root_identity(value: Any, *, preflight: Mapping[str, Any]) -> dict[str, Any]:
    row = _exact(value, DATA_ROOT_FIELDS, label="data-root identity")
    _require(row["schema"] == DATA_ROOT_SCHEMA,
             "DATA_ROOT_SCHEMA_MISMATCH", "data-root identity schema is unsupported")
    _diagnostic_markers(row, label="data-root identity")
    source = _root(row["source_data_root"], label="data-root source_data_root")
    reproduction = _root(row["reproduction_data_root"],
                         label="data-root reproduction_data_root")
    _require(source == preflight["source_data_root"]
             and reproduction == preflight["reproduction_data_root"],
             "DATA_ROOT_PREFLIGHT_MISMATCH",
             "data-root identity does not match typed preflight roots")
    _require(row["distinct_roots"] is True and source != reproduction,
             "DATA_ROOT_DISTINCTNESS_MISSING",
             "data-root identity does not close distinct-root binding")
    package_sha = _sha(row["package_sha256"], label="data-root package_sha256")
    _require(package_sha == preflight["package_sha256"],
             "DATA_ROOT_PACKAGE_MISMATCH",
             "data-root package hash differs from preflight")
    source_manifest = _sha(row["source_manifest_sha256"],
                           label="source_manifest_sha256")
    reproduction_manifest = _sha(row["reproduction_manifest_sha256"],
                                 label="reproduction_manifest_sha256")
    _require(source_manifest != reproduction_manifest,
             "MANIFEST_IDENTITIES_NOT_DISTINCT",
             "source and reproduction manifest identities are identical")
    expected_source = _identity_hash(source, source_manifest, package_sha)
    expected_reproduction = _identity_hash(reproduction, reproduction_manifest, package_sha)
    _require(row["source_identity_sha256"] == expected_source
             and row["reproduction_identity_sha256"] == expected_reproduction,
             "DATA_ROOT_IDENTITY_HASH_MISMATCH",
             "data-root identity hashes do not bind root, manifest and package")
    _require(row["manifest_binding_verified"] is True,
             "MANIFEST_BINDING_NOT_VERIFIED",
             "data-root projection does not assert its manifest binding")
    return {
        "source_data_root": source,
        "reproduction_data_root": reproduction,
        "package_sha256": package_sha,
        "source_manifest_sha256": source_manifest,
        "reproduction_manifest_sha256": reproduction_manifest,
        "source_identity_sha256": expected_source,
        "reproduction_identity_sha256": expected_reproduction,
        "projection_bound": True,
        "trusted": False,
    }


def _base_report() -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "status": "blocked",
        "passed": False,
        "structural_contract_passed": False,
        "readiness_pass": False,
        "diagnostic_only": True,
        **FALSE_CLAIMS,
        "execution_constraints": dict(EXECUTION_CONSTRAINTS),
        "mutations": dict(ZERO_MUTATIONS),
        "checks": {
            "typed_preflight_projection": False,
            "data_root_identity_binding": False,
            "trusted_root_review": False,
            "external_host_attestation": False,
            "non_diagnostic_full_product_evidence": False,
        },
        "bindings": None,
        "blockers": [],
        "errors": [],
        "interpretation": (
            "Synthetic bounded readiness contract only; it cannot authenticate a trusted root, "
            "mint external-host evidence, admit independent reproduction, or issue credit."
        ),
    }


def build_report(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one bounded projection and return a non-authorizing report."""
    report = _base_report()
    try:
        root = _exact(projection, INPUT_FIELDS, label="readiness projection")
        _require(root["schema"] == SCHEMA, "INPUT_SCHEMA_MISMATCH",
                 "readiness projection schema is unsupported")
        _require(root["input_origin"] == INPUT_ORIGIN,
                 "INPUT_ORIGIN_INVALID", "readiness projection is not synthetic_fixture")

        preflight = _validate_preflight(root["preflight"])
        data_roots = _validate_data_root_identity(
            root["data_root_identity"], preflight=preflight
        )
        trusted_root = _validate_root_review(root["trusted_root_review"])
        external_host = _validate_external_host(
            root["external_host_attestation"],
            expected_host_id=preflight["reproduction_host_id"],
        )

        report.update({
            "status": STRUCTURAL_BLOCKED_STATUS,
            "passed": True,
            "structural_contract_passed": True,
            "checks": {
                "typed_preflight_projection": True,
                "data_root_identity_binding": True,
                "trusted_root_review": False,
                "external_host_attestation": False,
                "non_diagnostic_full_product_evidence": False,
            },
            "bindings": {
                "source_host_id": preflight["source_host_id"],
                "reproduction_host_id": preflight["reproduction_host_id"],
                "source_data_root": data_roots["source_data_root"],
                "reproduction_data_root": data_roots["reproduction_data_root"],
                "package_sha256": data_roots["package_sha256"],
                "source_manifest_sha256": data_roots["source_manifest_sha256"],
                "reproduction_manifest_sha256": data_roots["reproduction_manifest_sha256"],
                "source_identity_sha256": data_roots["source_identity_sha256"],
                "reproduction_identity_sha256": data_roots["reproduction_identity_sha256"],
                "trusted_root_authenticated": trusted_root["authenticated"],
                "external_host_attested": external_host["attested"],
            },
            "blockers": [
                "trusted_root_review_missing_or_unauthenticated",
                "external_host_attestation_missing",
                "non_diagnostic_full_product_reproduction_missing",
            ],
            "next_required": [
                "obtain a real independently trusted root review receipt",
                "obtain a real external-host attestation bound to the reproduction host and root",
                "obtain non-diagnostic full-product evidence on another physical machine",
                "re-run the Core independent_reproduction gate verifier",
            ],
        })
    except ContractError as error:
        report["errors"] = [{"code": error.code, "message": str(error)}]
        report["blockers"] = ["invalid_or_untrusted_readiness_projection"]
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
    constraints = report.get("execution_constraints")
    if constraints != EXECUTION_CONSTRAINTS:
        errors.append("report.execution_constraints drift")
    if report.get("readiness_pass") is not False:
        errors.append("report.readiness_pass must remain false")
    status = report.get("status")
    if status == STRUCTURAL_BLOCKED_STATUS:
        if report.get("passed") is not True:
            errors.append("structural blocked report.passed must be true")
        if report.get("structural_contract_passed") is not True:
            errors.append("blocked structural report must retain structural_contract_passed")
        checks = report.get("checks")
        if not isinstance(checks, Mapping):
            errors.append("report.checks missing")
        else:
            expected_checks = {
                "typed_preflight_projection": True,
                "data_root_identity_binding": True,
                "trusted_root_review": False,
                "external_host_attestation": False,
                "non_diagnostic_full_product_evidence": False,
            }
            if dict(checks) != expected_checks:
                errors.append("structural blocked report.checks drift")
            if checks.get("data_root_identity_binding") is not True:
                errors.append("data-root identity binding must be true for synthetic fixture")
            if checks.get("trusted_root_review") is not False:
                errors.append("trusted-root check must remain false")
            if checks.get("external_host_attestation") is not False:
                errors.append("external-host check must remain false")
        bindings = report.get("bindings")
        if not isinstance(bindings, Mapping):
            errors.append("structural blocked report.bindings missing")
        else:
            if set(bindings) != BINDING_FIELDS:
                errors.append("structural blocked report.bindings fields are not exact")
            for key in ("trusted_root_authenticated", "external_host_attested"):
                if bindings.get(key) is not False:
                    errors.append(f"report.bindings.{key} must remain false")
            try:
                source_host = _text(bindings.get("source_host_id"), label="report source_host_id")
                reproduction_host = _text(
                    bindings.get("reproduction_host_id"),
                    label="report reproduction_host_id",
                )
                source_root = _root(bindings.get("source_data_root"), label="report source_data_root")
                reproduction_root = _root(
                    bindings.get("reproduction_data_root"),
                    label="report reproduction_data_root",
                )
                package_sha = _sha(bindings.get("package_sha256"), label="report package_sha256")
                source_manifest = _sha(
                    bindings.get("source_manifest_sha256"),
                    label="report source_manifest_sha256",
                )
                reproduction_manifest = _sha(
                    bindings.get("reproduction_manifest_sha256"),
                    label="report reproduction_manifest_sha256",
                )
                expected_source = _identity_hash(source_root, source_manifest, package_sha)
                expected_reproduction = _identity_hash(
                    reproduction_root, reproduction_manifest, package_sha
                )
                if source_host == reproduction_host or source_root == reproduction_root:
                    errors.append("report.bindings source/reproduction identities are not distinct")
                if source_manifest == reproduction_manifest:
                    errors.append("report.bindings source/reproduction manifests are not distinct")
                if bindings.get("source_identity_sha256") != expected_source:
                    errors.append("report.bindings.source_identity_sha256 mismatch")
                if bindings.get("reproduction_identity_sha256") != expected_reproduction:
                    errors.append("report.bindings.reproduction_identity_sha256 mismatch")
            except ContractError as error:
                errors.append(f"report.bindings invalid: {error.code}")
    elif status == INVALID_BLOCKED_STATUS:
        if report.get("passed") is not False:
            errors.append("invalid blocked report.passed must be false")
        if report.get("structural_contract_passed") is not False:
            errors.append("invalid blocked report must not be structurally passed")
        if not isinstance(report.get("errors"), list) or not report["errors"]:
            errors.append("invalid blocked report.errors must be non-empty")
    else:
        errors.append("report.status is unsupported")
    return errors


def synthetic_projection() -> dict[str, Any]:
    """Return the bounded fixture used for the non-authorizing report."""
    source_root = "/synthetic/core/source-root"
    reproduction_root = "/synthetic/core/reproduction-root"
    package_sha = "a" * 64
    source_manifest = "b" * 64
    reproduction_manifest = "c" * 64
    return {
        "schema": SCHEMA,
        "input_origin": INPUT_ORIGIN,
        "preflight": {
            "schema": PREFLIGHT_SCHEMA,
            "status": "pass",
            "structural_preflight_passed": True,
            "typed_chain_complete": True,
            "distinct_physical_hosts": True,
            "distinct_data_roots": True,
            "source_host_id": "synthetic-source-host",
            "reproduction_host_id": "synthetic-reproduction-host",
            "source_data_root": source_root,
            "reproduction_data_root": reproduction_root,
            "package_sha256": package_sha,
            "diagnostic_only": True,
            "independent_reproduction": False,
            "full_product_reproduction": False,
            "credit": 0,
            "qualification_credit": 0,
            "input_origin": INPUT_ORIGIN,
        },
        "trusted_root_review": {
            "schema": TRUSTED_ROOT_SCHEMA,
            "review_id": "synthetic-trusted-root-review-missing-v1",
            "root_id": "synthetic-root-not-authority",
            "decision": "not_attested",
            "authenticated": False,
            "authority_scope": "core.independent_reproduction",
            "review_ref": None,
            "input_origin": INPUT_ORIGIN,
            "diagnostic_only": True,
        },
        "external_host_attestation": {
            "schema": EXTERNAL_HOST_SCHEMA,
            "role": "reproduction_host",
            "host_id": "synthetic-reproduction-host",
            "hostname": "synthetic-reproduction-host",
            "attested": False,
            "receipt_present": False,
            "attestation_ref": None,
            "input_origin": INPUT_ORIGIN,
            "diagnostic_only": True,
        },
        "data_root_identity": {
            "schema": DATA_ROOT_SCHEMA,
            "source_data_root": source_root,
            "reproduction_data_root": reproduction_root,
            "distinct_roots": True,
            "package_sha256": package_sha,
            "source_manifest_sha256": source_manifest,
            "reproduction_manifest_sha256": reproduction_manifest,
            "source_identity_sha256": _identity_hash(source_root, source_manifest, package_sha),
            "reproduction_identity_sha256": _identity_hash(
                reproduction_root, reproduction_manifest, package_sha
            ),
            "manifest_binding_verified": True,
            "input_origin": INPUT_ORIGIN,
            "diagnostic_only": True,
        },
    }


def _read_projection(path: Path) -> Mapping[str, Any]:
    try:
        value, _, _ = read_bounded_json_object(
            path,
            label="readiness projection",
            max_bytes=MAX_INPUT_BYTES,
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
            write_json(args.output, report)
        except (OSError, ContractError) as error:
            report = _base_report()
            report["errors"] = [{"code": getattr(error, "code", "INPUT_ERROR"),
                                 "message": str(error)}]
            report["blockers"] = ["invalid_or_untrusted_readiness_projection"]
            write_json(args.output, report)
        return 0
    try:
        report, _, _ = read_bounded_json_object(
            args.report,
            label="A8 readiness report",
            max_bytes=MAX_INPUT_BYTES,
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
