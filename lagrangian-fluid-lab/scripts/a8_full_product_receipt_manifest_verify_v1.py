#!/usr/bin/env python3
"""Verify the A8 package-level full-product receipt boundary.

The existing A8 bridge and independent-reproduction preflight validate useful
projections, but they do not own one package-level equality check for a full
receipt, its manifest, and the three reader/prediction/scoring artifacts.  This
module supplies that missing boundary for bounded synthetic evidence only.

The verifier reads small JSON files below an explicitly supplied fixture root.
It binds every role to one package, case, attempt, nonce, reproduction host,
physical-host identity, data root, and raw SHA-256/byte count.  It also checks
the reader -> prediction -> scoring hash chain and requires the receipt's
artifact map to be exactly equal to the manifest's artifact map.

This is deliberately a non-authorizing boundary.  A structurally valid result
is ``verified_diagnostic_only``; it never authenticates a trusted root, proves
independent reproduction, mints checkpoint or qualification credit, or starts
any workload.  Unknown fields are rejected so a caller cannot add a positive
authority claim without making the package invalid.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import re
from typing import Any, Mapping


SCHEMA = "core.a8.full_product_receipt_manifest_verify.v1"
REPORT_SCHEMA = "core.a8.full_product_receipt_manifest_verify_report.v1"
MANIFEST_SCHEMA = "core.a8.full_product_package_manifest.v1"
RECEIPT_SCHEMA = "core.a8.full_product_receipt.v1"
INPUT_ORIGIN = "synthetic_fixture"
MAX_JSON_BYTES = 256 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
ROLES = ("reader", "prediction", "scoring")

ROLE_SCHEMAS = {
    "reader": "core.a8.synthetic.reader_artifact.v1",
    "prediction": "core.a8.synthetic.prediction_artifact.v1",
    "scoring": "core.a8.synthetic.scoring_artifact.v1",
}

MANIFEST_FIELDS = frozenset({
    "schema", "package_id", "case_id", "attempt_id", "nonce", "input_origin",
    "package_sha256", "source", "reproduction", "artifacts",
    "diagnostic_only", "full_product_reproduction", "independent_reproduction",
    "checkpoint", "credit",
})
RECEIPT_FIELDS = frozenset({
    "schema", "package_id", "case_id", "attempt_id", "nonce", "input_origin",
    "package_sha256", "source", "reproduction", "manifest", "artifact_bindings",
    "chain", "diagnostic_only", "full_product_reproduction",
    "independent_reproduction", "checkpoint", "credit",
})
IDENTITY_FIELDS = frozenset({
    "host_id", "physical_host_id", "data_root", "package_sha256",
})
ARTIFACT_REF_FIELDS = frozenset({
    "role", "path", "sha256", "bytes", "schema", "package_id", "case_id",
    "attempt_id", "nonce", "host_id", "physical_host_id", "data_root",
    "package_sha256",
})
MANIFEST_REF_FIELDS = frozenset({"path", "sha256", "bytes"})
CHAIN_FIELDS = frozenset({
    "reader_artifact_sha256", "prediction_reader_input_sha256",
    "prediction_artifact_sha256", "scoring_reader_input_sha256",
    "scoring_prediction_input_sha256", "scoring_artifact_sha256",
})
COMMON_ARTIFACT_FIELDS = frozenset({
    "schema", "role", "package_id", "case_id", "attempt_id", "nonce",
    "package_sha256", "host_id", "physical_host_id", "data_root",
    "input_origin", "diagnostic_only", "full_product_reproduction",
    "independent_reproduction", "checkpoint", "credit",
})
ARTIFACT_FIELDS = {
    "reader": COMMON_ARTIFACT_FIELDS | frozenset({"reader_complete"}),
    "prediction": COMMON_ARTIFACT_FIELDS | frozenset({
        "reader_input_sha256", "prediction_complete", "autonomous",
        "full_horizon", "future_state_inputs",
    }),
    "scoring": COMMON_ARTIFACT_FIELDS | frozenset({
        "reader_input_sha256", "prediction_input_sha256", "scoring_complete",
        "denominator_closed", "cases",
    }),
}

ZERO_MUTATIONS = {
    "registry": 0,
    "ledger": 0,
    "denominator": 0,
    "gate": 0,
    "completion": 0,
}


class VerifyError(ValueError):
    """A stable, fail-closed package verification error."""

    def __init__(self, code: str, message: str, *, role: str | None = None):
        super().__init__(message)
        self.code = code
        self.role = role


def _require(condition: bool, code: str, message: str, *, role: str | None = None) -> None:
    if not condition:
        raise VerifyError(code, message, role=role)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise VerifyError("NON_CANONICAL_JSON", "value cannot be represented as canonical JSON") from error


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any, *, label: str, role: str | None = None) -> str:
    _require(type(value) is str and SHA256_RE.fullmatch(value) is not None,
             "SHA256_INVALID", f"{label} is not a lowercase SHA-256 digest", role=role)
    return value


def _text(value: Any, *, label: str, role: str | None = None) -> str:
    _require(type(value) is str and bool(value.strip()),
             "TEXT_MISSING", f"{label} must be a non-empty string", role=role)
    _require(value == value.strip(), "TEXT_NOT_NORMALIZED",
             f"{label} contains leading or trailing whitespace", role=role)
    return value


def _root(value: Any, *, label: str, role: str | None = None) -> str:
    raw = _text(value, label=label, role=role)
    _require(raw.startswith("/") and "\\" not in raw,
             "DATA_ROOT_INVALID", f"{label} must be an absolute POSIX root", role=role)
    parts = raw.split("/")
    _require(".." not in parts, "DATA_ROOT_INVALID", f"{label} contains '..'", role=role)
    normalized = posixpath.normpath(raw)
    _require(normalized == raw and normalized not in ("", ".", "/"),
             "DATA_ROOT_NOT_CANONICAL", f"{label} is not a canonical non-root path", role=role)
    return normalized


def _exact(value: Any, fields: frozenset[str], *, label: str, role: str | None = None) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "OBJECT_REQUIRED", f"{label} must be an object", role=role)
    _require(set(value) == set(fields), "FIELDS_NOT_EXACT",
             f"{label} fields are not exact", role=role)
    return value


def _authority(value: Mapping[str, Any], *, label: str, role: str | None = None) -> None:
    _require(value.get("input_origin") == INPUT_ORIGIN, "INPUT_ORIGIN_INVALID",
             f"{label} is not a synthetic fixture", role=role)
    _require(value.get("diagnostic_only") is True, "DIAGNOSTIC_MARKER_INVALID",
             f"{label}.diagnostic_only must be true", role=role)
    _require(value.get("full_product_reproduction") is False,
             "FULL_PRODUCT_CLAIM_FORBIDDEN",
             f"{label}.full_product_reproduction must be false", role=role)
    _require(value.get("independent_reproduction") is False,
             "INDEPENDENT_REPRODUCTION_CLAIM_FORBIDDEN",
             f"{label}.independent_reproduction must be false", role=role)
    _require(type(value.get("checkpoint")) is int and value.get("checkpoint") == 0,
             "CHECKPOINT_CLAIM_FORBIDDEN", f"{label}.checkpoint must be zero", role=role)
    _require(type(value.get("credit")) is int and value.get("credit") == 0,
             "CREDIT_CLAIM_FORBIDDEN", f"{label}.credit must be zero", role=role)


def _relative_path(value: Any, *, label: str, role: str | None = None) -> str:
    path = _text(value, label=label, role=role)
    parsed = Path(path)
    _require(not parsed.is_absolute() and ".." not in parsed.parts,
             "ARTIFACT_PATH_INVALID", f"{label} must be a relative path without '..'", role=role)
    _require(path != "." and parsed.as_posix() == path,
             "ARTIFACT_PATH_NOT_CANONICAL", f"{label} is not a canonical POSIX path", role=role)
    return path


def _safe_json(path: str | Path, root: Path, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = Path(path).expanduser()
    _require(not candidate.is_symlink(), "SYMLINK_FORBIDDEN", f"{label} is a symlink")
    resolved_root = root.expanduser().resolve()
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as error:
        raise VerifyError("PATH_OUTSIDE_FIXTURE_ROOT", f"{label} is outside fixture root") from error
    _require(relative.as_posix() not in ("", "."), "PATH_NOT_FILE", f"{label} points to the fixture root")
    _require(resolved.is_file(), "JSON_FILE_MISSING", f"{label} is not a regular file")
    size = resolved.stat().st_size
    _require(size <= MAX_JSON_BYTES, "JSON_FILE_TOO_LARGE",
             f"{label} exceeds the bounded JSON limit")
    try:
        raw = resolved.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerifyError("JSON_READ_FAILED", f"{label} cannot be read as bounded JSON") from error
    _require(isinstance(value, dict), "JSON_OBJECT_REQUIRED", f"{label} must contain an object")
    return value, {
        "path": relative.as_posix(),
        "sha256": _sha256(raw),
        "bytes": len(raw),
    }


def _validate_identity(value: Any, *, label: str, package_sha256: str) -> dict[str, str]:
    row = _exact(value, IDENTITY_FIELDS, label=label)
    host_id = _text(row.get("host_id"), label=f"{label}.host_id")
    physical_host_id = _text(row.get("physical_host_id"), label=f"{label}.physical_host_id")
    data_root = _root(row.get("data_root"), label=f"{label}.data_root")
    declared_package = _valid_sha(row.get("package_sha256"), label=f"{label}.package_sha256")
    _require(declared_package == package_sha256, "PACKAGE_IDENTITY_MISMATCH",
             f"{label} package hash differs from the manifest package hash")
    return {
        "host_id": host_id,
        "physical_host_id": physical_host_id,
        "data_root": data_root,
        "package_sha256": declared_package,
    }


def _validate_ref(value: Any, *, role: str, label: str) -> dict[str, Any]:
    row = _exact(value, ARTIFACT_REF_FIELDS, label=label, role=role)
    _require(row.get("role") == role, "ROLE_IDENTITY_MISMATCH",
             f"{label}.role does not match its map key", role=role)
    _relative_path(row.get("path"), label=f"{label}.path", role=role)
    _valid_sha(row.get("sha256"), label=f"{label}.sha256", role=role)
    _require(type(row.get("bytes")) is int and row.get("bytes") >= 0,
             "BYTES_INVALID", f"{label}.bytes must be a non-negative integer", role=role)
    _require(row.get("schema") == ROLE_SCHEMAS[role], "ARTIFACT_SCHEMA_MISMATCH",
             f"{label}.schema is not the role schema", role=role)
    for field in ("package_id", "case_id", "attempt_id", "nonce", "host_id",
                  "physical_host_id", "data_root"):
        _text(row.get(field), label=f"{label}.{field}", role=role)
    _valid_sha(row.get("package_sha256"), label=f"{label}.package_sha256", role=role)
    return dict(row)


def _validate_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    row = _exact(payload, MANIFEST_FIELDS, label="package manifest")
    _require(row.get("schema") == MANIFEST_SCHEMA, "MANIFEST_SCHEMA_MISMATCH",
             "package manifest schema is unsupported")
    _authority(row, label="package manifest")
    package_id = _text(row.get("package_id"), label="package manifest.package_id")
    case_id = _text(row.get("case_id"), label="package manifest.case_id")
    attempt_id = _text(row.get("attempt_id"), label="package manifest.attempt_id")
    nonce = _text(row.get("nonce"), label="package manifest.nonce")
    package_sha256 = _valid_sha(row.get("package_sha256"), label="package manifest.package_sha256")
    source = _validate_identity(row.get("source"), label="manifest.source", package_sha256=package_sha256)
    reproduction = _validate_identity(
        row.get("reproduction"), label="manifest.reproduction", package_sha256=package_sha256
    )
    _require(source["host_id"] != reproduction["host_id"], "DUPLICATE_HOST_IDENTITY",
             "source and reproduction host ids are identical")
    _require(source["physical_host_id"] != reproduction["physical_host_id"],
             "DUPLICATE_PHYSICAL_HOST_IDENTITY",
             "source and reproduction physical host ids are identical")
    _require(source["data_root"] != reproduction["data_root"], "DUPLICATE_DATA_ROOT",
             "source and reproduction data roots are identical")
    artifacts = _exact(row.get("artifacts"), frozenset(ROLES), label="manifest.artifacts")
    refs: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    hashes: set[str] = set()
    for role in ROLES:
        ref = _validate_ref(artifacts.get(role), role=role, label=f"manifest.artifacts.{role}")
        _require(ref["package_id"] == package_id and ref["case_id"] == case_id
                 and ref["attempt_id"] == attempt_id and ref["nonce"] == nonce,
                 "ARTIFACT_RUN_ID_MISMATCH",
                 f"{role} artifact is not bound to the manifest run identity", role=role)
        _require(ref["host_id"] == reproduction["host_id"]
                 and ref["physical_host_id"] == reproduction["physical_host_id"],
                 "ARTIFACT_HOST_MISMATCH",
                 f"{role} artifact is not bound to the reproduction host", role=role)
        _require(ref["data_root"] == reproduction["data_root"], "ARTIFACT_ROOT_MISMATCH",
                 f"{role} artifact is not bound to the reproduction data root", role=role)
        _require(ref["package_sha256"] == package_sha256, "ARTIFACT_PACKAGE_HASH_MISMATCH",
                 f"{role} artifact package hash differs from the manifest", role=role)
        _require(ref["path"] not in paths, "DUPLICATE_ARTIFACT_PATH",
                 "reader/prediction/scoring reuse one artifact path", role=role)
        _require(ref["sha256"] not in hashes, "DUPLICATE_ARTIFACT_DIGEST",
                 "reader/prediction/scoring reuse one artifact digest", role=role)
        paths.add(ref["path"])
        hashes.add(ref["sha256"])
        refs[role] = ref
    return {
        "package_id": package_id,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
        "package_sha256": package_sha256,
        "source": source,
        "reproduction": reproduction,
        "artifacts": refs,
    }


def _validate_manifest_ref(value: Any, *, observed: Mapping[str, Any]) -> None:
    row = _exact(value, MANIFEST_REF_FIELDS, label="receipt.manifest")
    _relative_path(row.get("path"), label="receipt.manifest.path")
    _valid_sha(row.get("sha256"), label="receipt.manifest.sha256")
    _require(type(row.get("bytes")) is int and row.get("bytes") >= 0,
             "BYTES_INVALID", "receipt.manifest.bytes must be a non-negative integer")
    _require(dict(row) == dict(observed), "MANIFEST_RECEIPT_BINDING_MISMATCH",
             "receipt manifest reference does not match the observed manifest")


def _validate_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    row = _exact(payload, RECEIPT_FIELDS, label="full-product receipt")
    _require(row.get("schema") == RECEIPT_SCHEMA, "RECEIPT_SCHEMA_MISMATCH",
             "full-product receipt schema is unsupported")
    _authority(row, label="full-product receipt")
    package_id = _text(row.get("package_id"), label="receipt.package_id")
    case_id = _text(row.get("case_id"), label="receipt.case_id")
    attempt_id = _text(row.get("attempt_id"), label="receipt.attempt_id")
    nonce = _text(row.get("nonce"), label="receipt.nonce")
    package_sha256 = _valid_sha(row.get("package_sha256"), label="receipt.package_sha256")
    source = _validate_identity(row.get("source"), label="receipt.source", package_sha256=package_sha256)
    reproduction = _validate_identity(
        row.get("reproduction"), label="receipt.reproduction", package_sha256=package_sha256
    )
    bindings = _exact(row.get("artifact_bindings"), frozenset(ROLES), label="receipt.artifact_bindings")
    refs: dict[str, dict[str, Any]] = {}
    for role in ROLES:
        refs[role] = _validate_ref(
            bindings.get(role), role=role, label=f"receipt.artifact_bindings.{role}"
        )
    chain = _exact(row.get("chain"), CHAIN_FIELDS, label="receipt.chain")
    chain_dict = dict(chain)
    for key, value in chain_dict.items():
        _valid_sha(value, label=f"receipt.chain.{key}")
    return {
        "package_id": package_id,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
        "package_sha256": package_sha256,
        "source": source,
        "reproduction": reproduction,
        "manifest": dict(row["manifest"]),
        "artifact_bindings": refs,
        "chain": chain_dict,
    }


def _validate_artifact(
    payload: Mapping[str, Any], *, role: str, ref: Mapping[str, Any], context: Mapping[str, Any]
) -> dict[str, Any]:
    row = _exact(payload, ARTIFACT_FIELDS[role], label=f"{role} artifact", role=role)
    _require(row.get("schema") == ROLE_SCHEMAS[role], "ARTIFACT_SCHEMA_MISMATCH",
             f"{role} artifact schema is unsupported", role=role)
    _require(row.get("role") == role, "ROLE_IDENTITY_MISMATCH",
             f"{role} artifact role is inconsistent", role=role)
    _authority(row, label=f"{role} artifact", role=role)
    for field in ("package_id", "case_id", "attempt_id", "nonce"):
        _require(row.get(field) == context[field], "ARTIFACT_RUN_ID_MISMATCH",
                 f"{role} artifact {field} differs from the manifest", role=role)
    _require(row.get("package_sha256") == context["package_sha256"],
             "ARTIFACT_PACKAGE_HASH_MISMATCH",
             f"{role} artifact package hash differs from the manifest", role=role)
    reproduction = context["reproduction"]
    _require(row.get("host_id") == reproduction["host_id"]
             and row.get("physical_host_id") == reproduction["physical_host_id"],
             "ARTIFACT_HOST_MISMATCH",
             f"{role} artifact host identity differs from the manifest", role=role)
    _require(row.get("data_root") == reproduction["data_root"], "ARTIFACT_ROOT_MISMATCH",
             f"{role} artifact data root differs from the manifest", role=role)
    for field in ("package_id", "case_id", "attempt_id", "nonce", "host_id",
                  "physical_host_id", "data_root", "package_sha256"):
        _require(row.get(field) == ref[field], "ARTIFACT_REF_PAYLOAD_MISMATCH",
                 f"{role} artifact payload does not match its manifest reference", role=role)
    if role == "reader":
        _require(row.get("reader_complete") is True, "READER_NOT_COMPLETE",
                 "reader artifact is not complete", role=role)
    elif role == "prediction":
        _require(row.get("reader_input_sha256") == context["artifacts"]["reader"]["sha256"],
                 "PREDICTION_READER_BINDING_MISMATCH",
                 "prediction does not bind the manifest reader digest", role=role)
        _require(row.get("prediction_complete") is True and row.get("autonomous") is True
                 and row.get("full_horizon") is True and row.get("future_state_inputs") is False,
                 "PREDICTION_CONTRACT_INVALID",
                 "prediction artifact is not an autonomous full-horizon diagnostic result", role=role)
    else:
        _require(row.get("reader_input_sha256") == context["artifacts"]["reader"]["sha256"]
                 and row.get("prediction_input_sha256") == context["artifacts"]["prediction"]["sha256"],
                 "SCORING_CHAIN_BINDING_MISMATCH",
                 "scoring does not bind both upstream artifact digests", role=role)
        _require(row.get("scoring_complete") is True and row.get("denominator_closed") is True,
                 "SCORING_CONTRACT_INVALID",
                 "scoring artifact does not close its synthetic denominator", role=role)
        _require(row.get("cases") == [context["case_id"]], "SCORING_CASE_BINDING_MISMATCH",
                 "scoring cases do not exactly match the manifest case", role=role)
    return dict(row)


def _compare_run_identity(left: Mapping[str, Any], right: Mapping[str, Any], *, label: str) -> None:
    _require(left == right, "RECEIPT_MANIFEST_IDENTITY_MISMATCH",
             f"receipt and manifest {label} identity differs")


def _base_report() -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "version": "a8-full-product-receipt-manifest-verify-v1",
        "status": "blocked_fail_closed",
        "passed": False,
        "package_binding_verified": False,
        "input_origin": INPUT_ORIGIN,
        "diagnostic_only": True,
        "full_product_reproduction": False,
        "independent_reproduction": False,
        "checkpoint": 0,
        "credit": 0,
        "formal_admission": False,
        "qualification_credit": 0,
        "mutations": dict(ZERO_MUTATIONS),
        "execution_constraints": {
            "read_only": True,
            "synthetic_fixture_only": True,
            "production_bundle_read": False,
            "large_asset_read": False,
            "workload_started": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "root_or_privileged_execution": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "verification": {
            "manifest_receipt_exact": False,
            "reader_exact": False,
            "prediction_exact": False,
            "scoring_exact": False,
            "reader_prediction_scoring_chain_complete": False,
            "host_identity_distinct": False,
            "data_root_distinct": False,
        },
        "errors": [],
        "external_blockers": [
            "trusted_root_attestation_not_supplied",
            "independently_attested_external_host_not_supplied",
            "full_product_runtime_terminal_receipt_not_supplied",
            "formal_checkpoint_and_qualification_credit_unavailable",
        ],
        "interpretation": (
            "A structurally verified synthetic package is diagnostic evidence only. "
            "This boundary never authorizes full-product or independent reproduction."
        ),
    }


def verify(*, fixture_root: str | Path, manifest_path: str | Path,
           receipt_path: str | Path) -> dict[str, Any]:
    """Verify one bounded synthetic manifest/receipt package and return a report."""
    report = _base_report()
    root = Path(fixture_root).expanduser().resolve()
    try:
        _require(root.is_dir(), "FIXTURE_ROOT_MISSING", "fixture root is not a directory")
        manifest, manifest_ref = _safe_json(manifest_path, root, label="package manifest")
        receipt, receipt_ref = _safe_json(receipt_path, root, label="full-product receipt")
        context = _validate_manifest(manifest)
        receipt_context = _validate_receipt(receipt)
        _compare_run_identity(
            {key: context[key] for key in ("package_id", "case_id", "attempt_id", "nonce", "package_sha256")},
            {key: receipt_context[key] for key in ("package_id", "case_id", "attempt_id", "nonce", "package_sha256")},
            label="package/case/attempt/nonce",
        )
        _compare_run_identity(context["source"], receipt_context["source"], label="source")
        _compare_run_identity(context["reproduction"], receipt_context["reproduction"], label="reproduction")
        _validate_manifest_ref(receipt_context["manifest"], observed=manifest_ref)
        _require(receipt_context["artifact_bindings"] == context["artifacts"],
                 "RECEIPT_ARTIFACT_MAP_MISMATCH",
                 "receipt artifact bindings are not exactly equal to the manifest")

        observed_artifacts: dict[str, dict[str, Any]] = {}
        for role in ROLES:
            ref = context["artifacts"][role]
            payload, observed = _safe_json(root / ref["path"], root, label=f"{role} artifact")
            _require(observed["path"] == ref["path"], "ARTIFACT_PATH_MISMATCH",
                     f"{role} artifact path differs from manifest", role=role)
            _require(observed["sha256"] == ref["sha256"], "ARTIFACT_DIGEST_MISMATCH",
                     f"{role} artifact digest differs from manifest", role=role)
            _require(observed["bytes"] == ref["bytes"], "ARTIFACT_BYTES_MISMATCH",
                     f"{role} artifact byte count differs from manifest", role=role)
            _validate_artifact(payload, role=role, ref=ref, context=context)
            observed_artifacts[role] = observed

        chain = receipt_context["chain"]
        expected_chain = {
            "reader_artifact_sha256": context["artifacts"]["reader"]["sha256"],
            "prediction_reader_input_sha256": context["artifacts"]["reader"]["sha256"],
            "prediction_artifact_sha256": context["artifacts"]["prediction"]["sha256"],
            "scoring_reader_input_sha256": context["artifacts"]["reader"]["sha256"],
            "scoring_prediction_input_sha256": context["artifacts"]["prediction"]["sha256"],
            "scoring_artifact_sha256": context["artifacts"]["scoring"]["sha256"],
        }
        _require(chain == expected_chain, "RECEIPT_CHAIN_MISMATCH",
                 "receipt reader/prediction/scoring chain does not match manifest artifacts")
        report.update({
            "status": "verified_diagnostic_only",
            "passed": True,
            "package_binding_verified": True,
            "package": {
                "manifest": manifest_ref,
                "receipt": receipt_ref,
                "package_id": context["package_id"],
                "case_id": context["case_id"],
                "attempt_id": context["attempt_id"],
                "nonce": context["nonce"],
                "package_sha256": context["package_sha256"],
                "artifacts": observed_artifacts,
            },
            "verification": {
                "manifest_receipt_exact": True,
                "reader_exact": True,
                "prediction_exact": True,
                "scoring_exact": True,
                "reader_prediction_scoring_chain_complete": True,
                "host_identity_distinct": context["source"]["physical_host_id"]
                != context["reproduction"]["physical_host_id"],
                "data_root_distinct": context["source"]["data_root"]
                != context["reproduction"]["data_root"],
            },
        })
    except VerifyError as error:
        report["errors"] = [{"code": error.code, "role": error.role, "message": str(error)}]
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        report["errors"] = [{
            "code": "VERIFY_INPUT_ERROR",
            "role": None,
            "message": f"{type(error).__name__}: {error}",
        }]
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate that a verifier report cannot carry authority or mutation."""
    errors: list[str] = []
    for key, expected in {
        "schema": REPORT_SCHEMA,
        "input_origin": INPUT_ORIGIN,
        "diagnostic_only": True,
        "full_product_reproduction": False,
        "independent_reproduction": False,
        "checkpoint": 0,
        "credit": 0,
        "formal_admission": False,
        "qualification_credit": 0,
    }.items():
        if report.get(key) != expected:
            errors.append(f"{key} must be {expected!r}")
    if report.get("mutations") != ZERO_MUTATIONS:
        errors.append("mutations must remain zero")
    constraints = report.get("execution_constraints")
    if not isinstance(constraints, Mapping):
        errors.append("execution_constraints missing")
    else:
        for key, expected in (
            ("production_bundle_read", False), ("large_asset_read", False),
            ("workload_started", False), ("solver_started", False),
            ("worker_started", False), ("gpu_started", False),
            ("queue_mutation", 0), ("root_or_privileged_execution", False),
        ):
            if constraints.get(key) != expected:
                errors.append(f"execution_constraints.{key} must be {expected!r}")
    return sorted(set(errors))


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = verify(
        fixture_root=args.fixture_root,
        manifest_path=args.manifest,
        receipt_path=args.receipt,
    )
    _write_new_json(args.output, report)
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "passed": report["passed"],
        "credit": report["credit"],
    }, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
